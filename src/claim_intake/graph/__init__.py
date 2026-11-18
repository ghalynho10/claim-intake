"""The LangGraph flow: extract, pause for review in its own node, then save.

Built by feature 5 (intake and cited extraction). The LangGraph `thread_id` is
the claim's UUID; the checkpointer uses the `langgraph` schema.
"""
