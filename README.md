# ADVAYA — Hacktoberfest Triage Agent

A GitHub issue triage assistant that reviews issue context, checks related issues and repository code, and recommends labels and next steps. **GitHub changes require explicit human approval.**

Built by **Team Advaya**: Vinay R, Nithin M, Divyashree, and Rakshitha.

## Features

- Review issue details and compare related issues to help spot duplicates.
- Search the local repository clone for relevant code.
- Produce validated labels, severity, a summary, and recommended next steps.
- Queue proposed labels for explicit human approval.
- Show the agent's tool observations and activity log.
- Fall back to human review if model output or a dependency is unreliable.
- Responsive, light-colour dashboard built with plain HTML, CSS, and JavaScript.

## Project structure

\`\`\`text
hacktoberfest-triage-agent/
├── app.py
├── agent.py
├── llm.py
├── tools.py
├── requirements.txt
├── .env.example
├── .gitignore
└── static/
    └── index.html
\`\`\`

## Run in VS Code (Windows)

Install Python 3.11+, Git, and [Ollama](https://ollama.com/) if using a local model. Open the repository folder in VS Code and choose **Terminal → New Terminal**.

Create a virtual environment and install dependencies:

\`\`\`powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
\`\`\`

If PowerShell blocks activation, run \`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass\` and activate again.

In a separate terminal, start the default open-weight model:

\`\`\`powershell
ollama pull qwen2.5:7b-instruct
ollama serve
\`\`\`

Choose a GitHub repository you own or have permission to access. Use a separate test repository for trying approved writes. In the terminal where Flask will run, configure:

\`\`\`powershell
$env:DEMO_REPO = "YOUR_GITHUB_USERNAME/YOUR_TEST_REPOSITORY"
$env:GITHUB_TOKEN = "YOUR_GITHUB_PERSONAL_ACCESS_TOKEN"
\`\`\`

Use a fine-grained token restricted to the test repository and grant only the required issue permissions. Public repositories can be read without a token, but rate limits are lower. **Never put your real token in source code or commit it to GitHub.** The \`.env.example\` file is documentation only and is not automatically loaded.

Start the app:

\`\`\`powershell
python app.py
\`\`\`

Open [http://localhost:8000](http://localhost:8000). Keep Flask and the model server running.

## Using the dashboard

1. Check the API and repository status.
2. Select a recent issue or enter its number.
3. Click **Run triage** and wait for the result.
4. Review labels, severity, summary, possible duplicates, confidence, next steps, and the activity log.
5. Click **Propose labels for approval** to add suggestions to the approval queue.
6. Review each proposal and explicitly approve or deny it.

The model cannot approve its own proposals. Pending proposals are stored in memory and cleared when Flask restarts. Test writes only against a repository you control.

## API endpoints

| Endpoint | Purpose |
|---|---|
| \`GET /api/health\` | Model, backend, and repository status |
| \`GET /api/issues\` | Recent repository issues |
| \`GET /api/pending\` | Pending proposals |
| \`POST /api/triage\` | Analyse an issue |
| \`POST /api/propose\` | Create a label proposal |
| \`POST /api/approve\` | Approve or deny a proposal |

## Notes

Confidence is a model self-assessment, not a calibrated probability. Repository code search is substring-based and can miss paraphrased matches. If the model or GitHub API is unavailable, review the result manually. This is a hackathon prototype, not a replacement for maintainer judgement.

## License

MIT. See [LICENSE](LICENSE).
