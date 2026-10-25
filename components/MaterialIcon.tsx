type IconName = "arrow_forward" | "arrow_outward" | "undo" | "close" | "chevron_left" | "chevron_right";

export default function MaterialIcon({ name }: { name: IconName }) {
  return <span className="material-icon" aria-hidden="true">{name}</span>;
}
