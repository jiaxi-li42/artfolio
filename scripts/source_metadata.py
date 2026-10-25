"""Source metadata from explicit article containers; never infer credits from prose."""
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup


def text(node):
    return node.get_text(" ", strip=True) if node else ""


def normalized(value):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", value).casefold())


def lines(node):
    if not node:
        return []
    copy = BeautifulSoup(str(node), "html.parser")
    for br in copy.select("br"):
        br.replace_with("\n")
    for block in copy.select("p,li,h1,h2,h3,h4,div"):
        block.append("\n")
    return [value for line in copy.get_text(" ").splitlines() if (value := " ".join(line.split()))]


def links(node, url):
    result, seen = [], set()
    anchors = ([node] if node and node.name == "a" and node.get("href") else []) + (node.select("a[href]") if node else [])
    for anchor in anchors:
        href = urljoin(url, anchor["href"])
        if urlsplit(href).scheme in {"http", "https"} and href not in seen:
            result.append({"label": text(anchor) or href, "url": href})
            seen.add(href)
    return result


def extract_subtitle(site, soup):
    if site == "aperture":
        heading = soup.select_one("h1")
        header = heading.find_parent(class_="fl-col-content") if heading else None
        node = header.select_one(".subtitle, .fl-module-rich-text .fl-rich-text") if header else None
        return text(node) or None
    if site == "itsnicethat":
        node = soup.select_one(".fullscreen-article-header .rich-text")
        return text(node) or None
    return None


def reference_sections(node, url):
    """One Elementor widget may contain several explicitly titled sections."""
    labels = {"notes": "Notes", "references": "References", "bibliography": "Bibliography", "imagesources": "Image sources"}
    sections, label = {}, None
    for value in lines(node):
        if normalized(value) in labels:
            label = labels[normalized(value)]
            sections.setdefault(label, [])
        elif label:
            sections[label].append(value)
    result = {label: {"text": "\n".join(values), "links": []} for label, values in sections.items() if values}
    label = None
    for element in node.descendants:
        if element.name in {"p", "strong", "b", "h1", "h2", "h3", "h4"} and normalized(text(element)) in labels:
            label = labels[normalized(text(element))]
        elif element.name == "a" and label in result:
            result[label]["links"].extend(links(element, url))
    return result


def extract_reading_body(site, soup, metadata, captions=()):
    selectors = {"teeth": ".article__right__body", "aperture": ".post-content-column", "itsnicethat": "article",
                 "c41": ".post-content", "phroom": '[data-elementor-type="wp-post"]'}
    source = soup.select_one(selectors[site])
    if source is None:
        raise ValueError("Source body structure changed")
    body = BeautifulSoup(str(source), "html.parser")
    if site == "phroom":
        for index, node in enumerate(body.select(".elementor-widget-text-editor")):
            if index in metadata["body_exclusion_indexes"]:
                node.decompose()
        for node in body.select(".elementor-widget-text-editor"):
            if text(node) in captions:
                node.decompose()
        for node in body.select(".elementor-heading-title"):
            node.decompose()
    if site == "itsnicethat":
        for heading in body.select("h3"):
            if text(heading) == "Share Article" and heading.parent.select_one(".social-share"):
                heading.parent.decompose()
    for node in body.select("script,style,noscript,figcaption,.wp-caption-text,.gallery-caption,.post-credits,.margin-credits,.article_author_bio,.module-cluster,.module-newsletter,.extra-detail,.fullscreen-article-header"):
        node.decompose()
    return [text(node) for node in body.select("p,h1,h2,h3,h4,li") if text(node) and not node.select("p,h1,h2,h3,h4,li")]


def extract_metadata(site, soup, url):
    """Return canonical Credits plus the exact selectors used to identify them."""
    groups, seen, authors, exclusions, profiles = {}, {}, [], [], []
    subtitle = extract_subtitle(site, soup)

    def add(label, value, node=None, selector="", extra_links=None):
        value = str(value or "").strip()
        clean_links = links(node, url) + (extra_links or [])
        key = normalized(value)
        if not value and not clean_links:
            return
        canonical_label = seen.get(key, label) if value else label
        group = groups.setdefault(canonical_label, {"label": canonical_label, "values": [], "links": [], "selectors": []})
        if value and key not in seen:
            group["values"].append(value)
            seen[key] = canonical_label
        for link in clean_links:
            if link["url"] not in {item["url"] for item in group["links"]}:
                group["links"].append(link)
        if selector and selector not in group["selectors"]:
            group["selectors"].append(selector)

    def author(name, role, node, selector):
        if name and not any(normalized(a["name"]) == normalized(name) and a["role"] == role for a in authors):
            authors.append({"name": name, "role": role, "evidence": text(node), "selector": selector})

    if site == "teeth":
        selector = ".article__left__information"
        node = soup.select_one(selector)
        team = []
        writer_links = []
        for line in lines(node):
            match = re.match(r"^Words(?:\s+by|:)\s*(.+)$", line, re.I)
            if match:
                author(match[1], "Words", node, selector)
                own_links = [link for link in links(node, url) if normalized(link["label"]) in normalized(match[1])]
                writer_links.extend(link["url"] for link in own_links)
                add("Words", match[1], selector=selector, extra_links=own_links)
            else:
                team.append(line)
        if team:
            add("Creative team", "\n".join(team), selector=selector, extra_links=[link for link in links(node, url) if link["url"] not in writer_links])

    elif site == "c41":
        for selector in [".post-credits", ".margin-credits"]:
            for node in soup.select(selector):
                for line in lines(node):
                    if re.match(r"^(?:Credits|Published on)\b", line, re.I):
                        continue
                    match = re.match(r"^(.{1,70}?)\s+by:?\s+(.+)$", line, re.I)
                    if not match:
                        add("Creative team", line, selector=selector)
                        continue
                    roles, name = match.groups()
                    for role in re.split(r"\s+and\s+", roles):
                        role = role[0].upper() + role[1:]
                        own_links = [link for link in links(node, url) if normalized(link["label"]) in normalized(name)]
                        if role.casefold() == "words":
                            author(name, "Words", node, selector)
                            add("Words", name, selector=selector, extra_links=own_links)
                        else:
                            add("Creative team", f"{role}: {name}", selector=selector, extra_links=own_links)

    elif site == "aperture":
        selector = '.post-editorial a[href*="/author/"], .horizontal_cover_terms_and_date > a[href*="/author/"], .horizontal_cover_terms_and_date > a[href*="/post-author/"]'
        for node in soup.select(selector):
            if not re.match(r"^By\s", text(node.parent)):
                continue
            author(text(node), "Words", node, selector)
            add("Words", text(node), node, selector)
        selector = ".article_author_bio"
        for node in soup.select(selector):
            add("Author", text(node), node, selector)
            profiles.append({"role": "author", "name": authors[0]["name"] if authors else None, "bio": text(node), "links": links(node, url)})
        body = soup.select_one(".post-content-column")
        for node in body.select("p,.article-rights,.article-copyright") if body else []:
            # Rights embedded in a figure stay with that image, including all-photographs notices.
            explicit = set(node.get("class", [])) & {"article-rights", "article-copyright"}
            if not node.find_parent(["figure", "figcaption"]) and (explicit or re.match(r"^(?:Copyright\s*(?:©|\d{4})|©)", text(node), re.I)):
                add("Rights", text(node), node, ".post-content-column p,.post-content-column .article-rights,.post-content-column .article-copyright")

    elif site == "phroom":
        base = '[data-elementor-type="wp-post"] .elementor-widget-text-editor'
        widgets = soup.select(base)
        if widgets:
            first = widgets[0]
            first_selector = f'{base}[data-id="{first.get("data-id")}"]' if re.fullmatch(r"[\w-]+", first.get("data-id", "")) else base
            first_lines = lines(first)
            artist = first_lines[0] if first_lines else ""
            biographies = {}
            for index, node in enumerate(widgets[1:], 1):
                name = text(node.select_one("p > strong,p > b"))
                value = text(node)
                remainder = value[len(name):].lstrip() if name and value.startswith(name) else ""
                if name and normalized(name) in normalized(text(first)) and re.match(r"^(?:is\b|,\s*born\b|\([^)]*\)\s+is\b)", remainder, re.I):
                    biographies[index] = name
            editorial = bool(biographies) and all(normalized(name) != normalized(artist) for name in biographies.values())
            if editorial:
                artist = next(iter(biographies.values()))
                subtitle = first_lines[1] if len(first_lines) > 1 and not re.match(r"^\d", first_lines[1]) else None
                author(artist, "Words", first, first_selector)
                add("Words", artist, selector=first_selector)
            project, names = [], []
            byline_urls = set()
            for line in first_lines:
                match = re.match(r"^(Text|Published) by:\s*(.+)$", line, re.I)
                if match:
                    role = "Words" if match[1].casefold() == "text" else "Publisher"
                    own_links = [link for link in links(first, url) if normalized(link["label"]) in normalized(match[2])]
                    byline_urls.update(link["url"] for link in own_links)
                    add(role, match[2], selector=first_selector, extra_links=own_links)
                    if role == "Words":
                        author(match[2], "Words", first, first_selector)
                elif editorial and re.fullmatch(r"\d{1,2}\s+[A-Za-z]+\s+\d{4}", line):
                    add("Date on source", line, selector=first_selector)
                elif not editorial and normalized(line) != normalized(artist) and line not in {link["label"] for link in links(first, url)}:
                    project.append(line)
            add("Project", "\n".join(project), selector=first_selector)
            artist_links = [link for link in links(first, url) if link["url"] not in byline_urls]
            for index, node in enumerate(widgets):
                widget_id = node.get("data-id", "")
                selector = f'{base}[data-id="{widget_id}"]' if re.fullmatch(r"[\w-]+", widget_id) else base
                value = text(node)
                name = biographies.get(index)
                if index == 0:
                    exclusions.append(index)
                elif name:
                    add("Author" if editorial else "Artist", "\n".join(lines(node)), node, selector, artist_links)
                    profiles.append({"role": "author" if editorial else "artist", "name": name, "bio": value, "links": links(node, url) + artist_links})
                    names.append(name)
                    exclusions.append(index)
                elif re.match(r"^(?:Notes|References|Bibliography)\b", value):
                    for label, section in reference_sections(node, url).items():
                        add(label, section["text"], selector=selector, extra_links=section["links"])
                    exclusions.append(index)
                elif re.match(r"^Copyright\s*(?:©|\d{4})", value, re.I):
                    add("Rights", value, node, selector)
                    exclusions.append(index)
            if not names:
                add("Artist", artist, selector=first_selector, extra_links=artist_links)

    elif site == "itsnicethat":
        selector = "#article-author"
        node = soup.select_one(selector)
        author(text(node), "Words", node, selector)
        add("Words", text(node), node, selector)
        for heading in soup.select(".extra-detail h3"):
            node = heading.parent.select_one(".rich-text")
            if text(heading) == "About the Author":
                add("Author", text(node), node, ".extra-detail .rich-text")
                profiles.append({"role": "author", "name": authors[0]["name"] if authors else None, "bio": text(node), "links": links(node, url)})
            elif text(heading) == "Further Info":
                add("Further info", "", node, ".extra-detail .rich-text")

    credits = [{"label": group["label"], "text": "\n".join(group["values"]), "links": group["links"]} for group in groups.values()]
    provenance = [{"label": group["label"], "selectors": group["selectors"]} for group in groups.values()]
    return {"authors": authors, "credits": credits, "profiles": profiles, "provenance": provenance, "body_exclusion_indexes": exclusions, "subtitle": subtitle}
