"""Session Memory — Per-thread checkpoint via AsyncPostgresSaver."""
# This is managed by LangGraph's AsyncPostgresSaver checkpointer.
# Configuration is in supervisor.py when compiling the graph.
# See: graph.compile(checkpointer=AsyncPostgresSaver(conn_string))
