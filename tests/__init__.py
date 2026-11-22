import engine.runs

# tests never read the repository's run_selection.json;
# selection tests set SELECTION_PATH to a temporary file and restore None.
engine.runs.SELECTION_PATH = None
