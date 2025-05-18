# GitHub Local Repository Viewer Generator

This Python script fetches data from a specified GitHub repository (files, pull requests, and diffs) and generates a static HTML website that allows you to browse the repository content and review pull request changes locally and offline.

## Features

* **GitHub API Interaction:** Connects to the GitHub API using a Personal Access Token (PAT) for authentication.
* **Local Caching:** All fetched data (API responses, file contents, PR details) is cached locally in a `_cache` subdirectory. Subsequent runs for the same repository will use cached data if available, significantly speeding up the process and reducing API calls.
* **Static HTML Site Generation:** Creates a browseable set of HTML files:
    * An `index.html` for the repository, listing files, directories, and open pull requests.
    * Individual HTML pages for each file in the repository.
    * Individual HTML pages for each open pull request, detailing its description and all file changes.
* **File Content Viewing:** Displays the content of text files. Provides messages for binary files or files exceeding a defined size limit.
* **Pull Request Change Visualization:**
    * **On Individual File Pages:**
        * A dropdown allows selecting a specific Pull Request relevant to the current file. This view shows the file's content as if that single PR's changes were applied, with additions highlighted and annotated with PR information (number and title on hover).
        * An option "Show All PR Additions (Interleaved View)" attempts to display the base file content with additions from *all* relevant PRs interleaved and annotated. This is a best-effort visualization for additions.
        * Links to the full local PR detail page and the PR on GitHub are provided.
    * **On Dedicated PR Pages:**
        * Displays the PR's title, author, description, and a list of all files changed.
        * For each changed file, the raw patch (diff) is rendered using `diff2html.js`, providing a clear side-by-side or line-by-line visual representation of the modifications within that PR.
* **Asset Management:** Automatically downloads `diff2html.js` and its CSS if not already present in the generated site's `assets` directory.
* **Pagination Handling:** Fetches all open pull requests, handling GitHub API pagination for the PR list.

## Prerequisites

1.  **Python:** Version 3.6 or newer.
2.  **`requests` Library:** If not already installed, you can install it via pip:
    ```bash
    pip install requests
    ```
3.  **GitHub Personal Access Token (PAT):** The script requires a PAT to authenticate with the GitHub API. This allows for higher rate limits and access to private repositories (if the token has the necessary permissions).

## Setup

### 1. Create a GitHub Personal Access Token (PAT)

* Go to your GitHub account settings.
* Navigate to **Developer settings** > **Personal access tokens** > **Tokens (classic)**.
* Click **"Generate new token"** (or "Generate new token (classic)").
* **Note:** Give your token a descriptive name (e.g., "Local Repo Viewer Script").
* **Expiration:** Set an appropriate expiration date for the token.
* **Scopes:** Select the necessary scopes:
    * For **public repositories** only: `public_repo` is usually sufficient.
    * For **private repositories**: you will need the full `repo` scope.
* Click **"Generate token"**.
* **Important:** Copy the generated token immediately. You will not be able to see it again after leaving the page.

### 2. Set the Environment Variable

The script expects your PAT to be available as an environment variable named `GITHUB_TOKEN`. Set this variable in your terminal session before running the script:

* **Linux/macOS:**
    ```bash
    export GITHUB_TOKEN="your_paste_token_here"
    ```
* **Windows (Command Prompt):**
    ```bash
    set GITHUB_TOKEN="your_paste_token_here"
    ```
* **Windows (PowerShell):**
    ```powershell
    $env:GITHUB_TOKEN="your_paste_token_here"
    ```
    Replace `"your_paste_token_here"` with your actual PAT.

## How to Run

1.  **Save the Script:** Save the Python code as a `.py` file (e.g., `generate_github_site.py`).
2.  **Open Terminal:** Navigate to the directory where you saved the script.
3.  **Run the Script:**
    ```bash
    python generate_github_site.py
    ```
4.  **Enter Repository Details:** The script will prompt you for:
    * The repository owner (e.g., `psf`).
    * The repository name (e.g., `requests`).
    Press Enter to use the default values if provided in the script.
5.  **Processing:** The script will begin fetching data. The first run for a repository might take some time, especially for large repositories, as it downloads and caches all necessary information. Subsequent runs will be faster.

## Output Structure

The script will create a main output directory (default: `gh_local_viewer_output`) in the same location where the script is run. Inside this, a structure for each processed repository will be created:

```
gh_local_viewer_output/
└── /
└── /
├── _cache/           # Stores cached API responses and file blobs
│   ├── dir_contents/
│   ├── file_blobs/
│   ├── pull_files_detail/
│   └── pulls_meta/
└── html/             # Contains the generated static HTML site
├── assets/       # diff2html.js and CSS
│   ├── diff2html-ui.min.js
│   └── diff2html.min.css
├── files/        # HTML pages for each file in the repo (mirrors repo structure)
│   └── path/
│       └── to/
│           └── file.py.html
├── pulls/        # HTML pages for each PR
│   └── 123.html
└── index.html    # Main entry point for the local site
```
To view the generated site, open the `html/index.html` file (located within the specific `<owner>/<repo>` directory) in your web browser. The script will print the full path to this file upon successful completion.

## Important Notes & Limitations

* **API Rate Limiting:** While the script uses authenticated requests (which have higher rate limits, typically 5000 requests/hour), fetching very large repositories or running the script very frequently for new repositories might still approach these limits. The caching mechanism significantly reduces API calls on subsequent runs for the same repository.
* **Large Repositories:** The initial processing of very large repositories (many files, large files, extensive PR history) can be time-consuming and may consume considerable disk space for the cache and HTML output.
* **PR Files Pagination:** The script fetches all open PRs using pagination. However, for the files within *each* PR (`/pulls/:pr_number/files` endpoint), it currently fetches only the first page (up to 300 files). For PRs with more than 300 changed files, not all changes will be listed on the PR detail page or considered for the file-specific views.
* **"Interleaved Merged View" for All PRs:** The "Show All PR Additions (Interleaved View)" on individual file pages is a *best-effort visualization* focusing on showing where lines were added by various PRs relative to the original base. It does not perform a true, sequential Git-style merge and may not perfectly represent complex, overlapping changes. For precise diffs, refer to the individual PR detail pages or the standard diff views.
* **Symlinks & Submodules:** The script primarily processes regular files and directories. While symlinks or submodules might be listed if they appear in the `/contents` API response, their specific content or targets are not deeply resolved or processed.
* **Error Handling:** Basic error handling for API requests and file operations is included. More extensive error handling could be added for production-grade robustness.
