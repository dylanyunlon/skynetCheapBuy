## Project philosophy
- Simple to get value
- Flexible and easy to add new own "AI steps". See `steps.py`.
- Incrementally build towards a user experience of:
  1. high level prompting
  2. giving feedback to the AI that it will remember over time
- Fast handovers back and forth between AI and human
- Simplicity, all computation is "resumable" and persisted to the filesystem

Input -> CLI/API -> Agent Service -> AI Engine -> Code Generation
    ↓                                         ↓
Terminal UI <-> WebSocket <-> Execution Engine -> Sandbox/Docker
    ↓                                         ↓
File System <-> Workspace Manager <-> Git Integration
    ↓                                         ↓
Debug Output <-> Debug Agent <-> Error Analysis -> Fix Suggestion

## Usage

**Setup**:
- `git clone`
- `unicorn`
**Run**:
- Create a new empty folder with a `main_prompt` file (or copy the example folder `cp -r example/ my-new-project`)
- Fill in the `main_prompt` in your new folder
**Results**:
- Check the generated files in my-new-project/workspace

## Features
You can specify the "identity" of the AI agent by editing the files in the `identity` folder.

Editing the identity, and evolving the main_prompt, is currently how you make the agent remember things between projects.

Each step in steps.py will have its communication history with Claude stored in the logs folder, and can be rerun with scripts/rerun_edited_message_logs.py.

### Next up
We have noticed that for complex projects the model is "lazy" in implementing many files.

Hence, we want to let LLM generate a new prompt for a "sub-engnieer" that goes through each file, takes other relevant files as context and rewrites the files.


### More things to try
- allow for human edits in the code/add comments and store those edits as diffs, to use as "feedback" in the future etc
- Add step of generating tests
- Fix code based on failing tests
- Allow for rerunning the entire run from scratch, but "replay" human diffs by adding the diffs to the prompt and asking LLM to apply them in the new code
- Allow for fine grained configuration, per project, so that it can be regenerated from scratch applying all the human diffs that came after the initial AI generation step. Which diffs come in which steps, etc.


5. **Start the server**
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### Caching
Redis-based caching for improved response times and reduced API costs.

### Database Management
Built-in migration system and connection pooling for optimal database performance.

### Configuration Management
Centralized configuration with environment-specific settings.

