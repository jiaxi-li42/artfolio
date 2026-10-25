"""Compatibility entry point for the checkpointed daily runner (--through supported)."""
from run_daily import main

if __name__ == '__main__':
    raise SystemExit(main())
