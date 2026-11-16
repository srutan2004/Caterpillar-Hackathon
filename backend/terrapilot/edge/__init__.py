"""Edge runtime (§2.3): fuses frames into MachineState and runs safety, behaviour and live copilot locally.
Must run with the network down; it never imports cloud modules (analytics, ml, planning, llm providers)."""
