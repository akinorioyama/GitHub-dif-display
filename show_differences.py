import requests
import json
import os
import base64
import html
import time
import shutil  # For rmtree, if uncommented
import re  # For parsing patch hunks

# --- Configuration ---
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')
if not GITHUB_TOKEN:
    print("Error: GITHUB_TOKEN environment variable not set.")
    print("Please generate a Personal Access Token from GitHub and set it as GITHUB_TOKEN.")
    print("Example (Linux/macOS): export GITHUB_TOKEN=\"your_token_here\"")
    print("Example (Windows CMD): set GITHUB_TOKEN=\"your_token_here\"")
    print("Example (Windows PowerShell): $env:GITHUB_TOKEN=\"your_token_here\"")
    exit(1)

OUTPUT_BASE_DIR = "gh_local_viewer_output2"  # Root directory for all generated sites
API_BASE_URL = "https://api.github.com"
HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json",  # Default API version
    "X-GitHub-Api-Version": "2022-11-28"  # Explicitly set API version
}

# diff2html asset URLs (using the UI bundle for simplicity)
DIFF2HTML_UI_JS_URL = "https://cdn.jsdelivr.net/npm/diff2html/bundles/js/diff2html-ui.min.js"
DIFF2HTML_CSS_URL = "https://cdn.jsdelivr.net/npm/diff2html/bundles/css/diff2html.min.css"
MAX_FILE_SIZE_FOR_CONTENT_DISPLAY = 5 * 1024 * 1024  # 5MB limit for displaying content directly in HTML to avoid browser lag


# --- Caching Utilities ---
def get_cache_path(owner, repo, cache_type, identifier=""):
    """
    Determines the file path for a cached item.
    cache_type: e.g., 'contents_metadata', 'file_content_blob', 'pulls_meta', 'pull_files_detail'
    identifier: A unique string for the item (e.g., path for contents, sha for blob, pr_number for pull_files)
    """
    base_cache_dir = os.path.join(OUTPUT_BASE_DIR, owner, repo, "_cache")

    sanitized_identifier = base64.urlsafe_b64encode(identifier.encode()).decode() if identifier else "default"

    if cache_type == 'file_content_blob':
        path = os.path.join(base_cache_dir, "file_blobs", f"{identifier}.dat")
    elif cache_type == 'contents_metadata':
        path = os.path.join(base_cache_dir, "dir_contents", f"{sanitized_identifier}.json")
    elif cache_type == 'pull_files_detail':
        path = os.path.join(base_cache_dir, cache_type, f"{str(identifier)}.json")
    elif identifier:
        path = os.path.join(base_cache_dir, cache_type, f"{sanitized_identifier}.json")
    else:
        path = os.path.join(base_cache_dir, f"{cache_type}.json")

    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path


def save_json_cache(file_path, data):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except Exception as e:
        print(f"Warning: Could not save JSON cache to {file_path}: {e}")


def load_json_cache(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Warning: Could not load or parse JSON cache from {file_path}: {e}")
            return None
    return None


def save_raw_cache(file_path, content_bytes):
    try:
        with open(file_path, 'wb') as f:
            f.write(content_bytes)
    except Exception as e:
        print(f"Warning: Could not save raw cache to {file_path}: {e}")


def load_raw_cache(file_path):
    if os.path.exists(file_path):
        try:
            with open(file_path, 'rb') as f:
                return f.read()
        except Exception as e:
            print(f"Warning: Could not load raw cache from {file_path}: {e}")
            return None
    return None


# --- GitHub API Interaction Class ---
class GitHubAPI:
    def __init__(self, owner, repo):
        self.owner = owner
        self.repo = repo
        self.rate_limit_remaining = None
        self.rate_limit_reset_time = None

    def _update_rate_limit_info(self, response_headers):
        if 'X-RateLimit-Remaining' in response_headers:
            self.rate_limit_remaining = int(response_headers['X-RateLimit-Remaining'])
        if 'X-RateLimit-Reset' in response_headers:
            self.rate_limit_reset_time = int(response_headers['X-RateLimit-Reset'])

    def _request(self, url, params=None, is_raw_content=False):
        try:
            response = requests.get(url, headers=HEADERS, params=params, timeout=30)
            self._update_rate_limit_info(response.headers)
            response.raise_for_status()

            if self.rate_limit_remaining is not None and self.rate_limit_remaining < 20:
                print(f"Warning: Low API rate limit remaining: {self.rate_limit_remaining}")

            if is_raw_content:
                return response.content
            return response.json()
        except requests.exceptions.HTTPError as e:
            print(f"HTTP Error: {e.response.status_code} for URL: {url}")
            print(f"Response: {e.response.text}")
        except requests.exceptions.RequestException as e:
            print(f"Request Error: {e} for URL: {url}")
        return None

    def get_repo_contents(self, dir_path=''):
        cache_file = get_cache_path(self.owner, self.repo, 'contents_metadata', dir_path)
        cached_data = load_json_cache(cache_file)
        if cached_data:
            return cached_data

        print(f"Fetching repo contents: '{dir_path if dir_path else "root"}'")
        url = f"{API_BASE_URL}/repos/{self.owner}/{self.repo}/contents/{dir_path}"
        data = self._request(url)
        if data:
            save_json_cache(cache_file, data)
        time.sleep(0.05)
        return data

    def get_file_blob_content(self, blob_sha):
        cache_file = get_cache_path(self.owner, self.repo, 'file_content_blob', blob_sha)
        cached_data = load_raw_cache(cache_file)
        if cached_data:
            return cached_data

        print(f"Fetching file blob: {blob_sha}")
        url = f"{API_BASE_URL}/repos/{self.owner}/{self.repo}/git/blobs/{blob_sha}"
        blob_metadata = self._request(url)

        if blob_metadata and blob_metadata.get('encoding') == 'base64' and 'content' in blob_metadata:
            try:
                content_base64 = blob_metadata['content'].replace('\n', '')
                decoded_bytes = base64.b64decode(content_base64)
                save_raw_cache(cache_file, decoded_bytes)
                time.sleep(0.05)
                return decoded_bytes
            except Exception as e:
                print(f"Error decoding base64 content for blob {blob_sha}: {e}")
        elif blob_metadata:
            print(f"Warning: Blob {blob_sha} content not base64 or 'content' field missing. Data: {blob_metadata}")

        time.sleep(0.05)
        return None

    def get_pull_requests(self, state='open', per_page=100):
        cache_file = get_cache_path(self.owner, self.repo, 'pulls_meta', state)
        cached_data = load_json_cache(cache_file)
        if cached_data is not None:
            return cached_data

        print(f"Fetching PR list (state: {state}), handling pagination...")
        all_pull_requests = []
        current_url = f"{API_BASE_URL}/repos/{self.owner}/{self.repo}/pulls"
        current_params = {'state': state, 'per_page': per_page, 'sort': 'updated', 'direction': 'desc'}
        page_num = 1
        while current_url:
            print(f"  Fetching PRs page {page_num}...")
            try:
                response = requests.get(current_url, headers=HEADERS, params=current_params, timeout=30)
                self._update_rate_limit_info(response.headers)
                response.raise_for_status()

                current_page_data = response.json()
                if not current_page_data: break
                all_pull_requests.extend(current_page_data)
                next_link_info = response.links.get('next')
                if next_link_info:
                    current_url = next_link_info['url']
                    current_params = None
                    page_num += 1
                else:
                    current_url = None
                time.sleep(0.05)
            except requests.exceptions.HTTPError as e:
                print(
                    f"HTTP Error: {e.response.status_code} while fetching PRs page {page_num} from {current_url.split('?')[0] if current_url else 'N/A'}")
                print(f"Response: {e.response.text}")
                current_url = None;
                all_pull_requests = [];
                break
            except requests.exceptions.RequestException as e:
                print(
                    f"Request Error: {e} while fetching PRs page {page_num} from {current_url.split('?')[0] if current_url else 'N/A'}")
                current_url = None;
                all_pull_requests = [];
                break
            except json.JSONDecodeError as e:
                print(
                    f"JSON Decode Error: {e} for PRs page {page_num} from {current_url.split('?')[0] if current_url else 'N/A'}. Response text: {response.text[:200]}...")
                current_url = None;
                all_pull_requests = [];
                break
        save_json_cache(cache_file, all_pull_requests)
        if all_pull_requests:
            print(f"  Fetched a total of {len(all_pull_requests)} PRs across {page_num} page(s).")
        elif page_num > 1 and not all_pull_requests:
            print(f"  Error occurred during PR fetch after {page_num - 1} page(s). Resulting list is empty.")
        else:
            print(f"  No PRs found or an error occurred on the first page for state: {state}.")
        return all_pull_requests

    def get_pull_request_files(self, pr_number):
        cache_file = get_cache_path(self.owner, self.repo, 'pull_files_detail', str(pr_number))
        cached_data = load_json_cache(cache_file)
        if cached_data: return cached_data
        print(f"Fetching files for PR #{pr_number} (first page)...")
        url = f"{API_BASE_URL}/repos/{self.owner}/{self.repo}/pulls/{pr_number}/files"
        params = {'per_page': 300}
        data = self._request(url, params=params)
        if data: save_json_cache(cache_file, data)
        time.sleep(0.05)
        return data


# --- Patch Application Utility ---
def apply_patch_to_content(base_content_str, patch_string, pr_details_for_annotation=None):
    """
    Applies a unidiff patch string to a base content string, returning HTML with highlights.
    If pr_details_for_annotation is provided, added lines are wrapped in spans with PR info.
    """
    if not patch_string:
        return html.escape(base_content_str) if base_content_str else ""
    if base_content_str is None:
        base_content_str = ""

    base_lines = base_content_str.splitlines()
    patched_lines_html_result = []

    raw_patch_lines = patch_string.splitlines()
    hunk_sections = []
    current_hunk_body = None
    current_hunk_header = None

    for line in raw_patch_lines:
        if line.startswith("@@"):
            if current_hunk_header is not None and current_hunk_body is not None:
                hunk_sections.append((current_hunk_header, current_hunk_body))
            current_hunk_header = line
            current_hunk_body = []
        elif current_hunk_body is not None:
            if line.startswith(("+", "-", " ", "\\")):
                current_hunk_body.append(line)
    if current_hunk_header is not None and current_hunk_body is not None:
        hunk_sections.append((current_hunk_header, current_hunk_body))

    if not hunk_sections:
        is_only_no_newline_meta = False
        if "\\ No newline at end of file" in patch_string:
            is_only_no_newline_meta = not any(
                pline.startswith(('+', '-')) for pline in raw_patch_lines
                if not pline.startswith(('@@', '---', '+++', 'diff', 'index', '\\')))
        if is_only_no_newline_meta:
            return html.escape(base_content_str)
        return html.escape(base_content_str)

    current_base_line_idx = 0

    for header_line, body_lines in hunk_sections:
        match = re.search(r"@@ -(\d+)(,(\d+))? \+(\d+)(,(\d+))? @@", header_line)
        if not match:
            continue

        old_start_1based = int(match.group(1))
        lines_to_copy_from_base_before_hunk = (old_start_1based - 1) - current_base_line_idx

        if lines_to_copy_from_base_before_hunk > 0:
            end_copy_idx = current_base_line_idx + lines_to_copy_from_base_before_hunk
            if end_copy_idx > len(base_lines): end_copy_idx = len(base_lines)
            for i in range(current_base_line_idx, end_copy_idx):
                patched_lines_html_result.append(html.escape(base_lines[i]))
            current_base_line_idx = end_copy_idx
        elif lines_to_copy_from_base_before_hunk < 0:
            if old_start_1based > 0:  # old_start_1based can be 0 for new files
                current_base_line_idx = old_start_1based - 1

        for hunk_body_line in body_lines:
            escaped_line_content = html.escape(hunk_body_line[1:])
            if hunk_body_line.startswith("+"):
                if pr_details_for_annotation:
                    pr_num = pr_details_for_annotation.get('number', 'N/A')
                    pr_title = html.escape(pr_details_for_annotation.get('title', 'Unknown PR'))
                    patched_lines_html_result.append(
                        f'<span class="added-line pr-annotated" title="PR #{pr_num}: {pr_title}">'
                        f'{escaped_line_content}</span>'
                    )
                else:
                    patched_lines_html_result.append(f'<span class="added-line">{escaped_line_content}</span>')
            elif hunk_body_line.startswith("-"):
                if current_base_line_idx < len(base_lines):
                    current_base_line_idx += 1
            elif hunk_body_line.startswith(" "):
                patched_lines_html_result.append(escaped_line_content)
                if current_base_line_idx < len(base_lines):
                    current_base_line_idx += 1
            elif hunk_body_line.startswith("\\"):
                pass

    if current_base_line_idx < len(base_lines):
        for i in range(current_base_line_idx, len(base_lines)):
            patched_lines_html_result.append(html.escape(base_lines[i]))

    return "\n".join(patched_lines_html_result)


# --- HTML Generation Utilities ---
def ensure_assets(assets_dir_abs):
    os.makedirs(assets_dir_abs, exist_ok=True)
    js_filename = "diff2html-ui.min.js";
    css_filename = "diff2html.min.css"
    js_path_abs = os.path.join(assets_dir_abs, js_filename);
    css_path_abs = os.path.join(assets_dir_abs, css_filename)
    assets_ok = True
    if not os.path.exists(js_path_abs):
        print(f"Downloading {js_filename}...");
        response_js = None
        try:
            response_js = requests.get(DIFF2HTML_UI_JS_URL, timeout=30);
            response_js.raise_for_status()
            with open(js_path_abs, 'w', encoding='utf-8') as f:
                f.write(response_js.text)
        except Exception as e:
            print(f"Failed to download {js_filename}: {e}"); assets_ok = False
    if not os.path.exists(css_path_abs):
        print(f"Downloading {css_filename}...");
        response_css = None
        try:
            response_css = requests.get(DIFF2HTML_CSS_URL, timeout=30);
            response_css.raise_for_status()
            with open(css_path_abs, 'w', encoding='utf-8') as f:
                f.write(response_css.text)
        except Exception as e:
            print(f"Failed to download {css_filename}: {e}"); assets_ok = False
    return assets_ok


def generate_file_html_page(owner, repo, file_info, base_content_str, is_binary, is_too_large,
                            relevant_prs_info, html_file_path_abs, assets_rel_path, pulls_dir_rel_path,
                            all_prs_interleaved_lines_json):
    file_path_display = html.escape(file_info['path'])
    pr_options_html = '<option value="base_content">Show Base Content</option>'
    # Changed option value to match JS, and text for clarity
    pr_options_html += '<option value="all_pr_changes_interleaved">Show All PR Additions (Interleaved View)</option>'

    js_pr_data = {}

    for pr_num_int, pr_data in relevant_prs_info.items():
        pr_num_str = str(pr_num_int)
        pr_title_escaped = html.escape(f"#{pr_num_str}: {pr_data['title']}")
        pr_options_html += f'<option value="{pr_num_str}">{pr_title_escaped}</option>'

        js_pr_data[pr_num_str] = {
            "title": pr_data['title'],
            "patch": pr_data.get('patch_for_this_file'),
            "html_url": pr_data['html_url'],
            "merged_content_html": pr_data.get('merged_content_html_for_this_file'),
            "local_pr_page_link": os.path.join(pulls_dir_rel_path, f"{pr_num_str}.html").replace("\\", "/")
        }

    if is_binary:
        base_content_html_escaped = html.escape(
            f"[Binary File - Content not displayed. Size: {file_info.get('size', 0)} bytes]")
    elif is_too_large:
        base_content_html_escaped = html.escape(
            f"[File Too Large ({file_info.get('size', 0) // 1024}KB) - Content not displayed directly.]")
    elif base_content_str is not None:
        base_content_html_escaped = html.escape(base_content_str)
    else:
        base_content_html_escaped = html.escape("[Content not available or error fetching content]")

    html_file_dir_abs = os.path.dirname(html_file_path_abs)
    html_output_dir_abs = os.path.abspath(os.path.join(html_file_dir_abs, ".."))
    index_rel_path = os.path.relpath(os.path.join(html_output_dir_abs, "index.html"), html_file_dir_abs).replace("\\",
                                                                                                                 "/")

    html_template = f"""
<!DOCTYPE html><html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{file_path_display} - {owner}/{repo}</title>
    <link rel="stylesheet" type="text/css" href="{assets_rel_path}/diff2html.min.css">
    <style>
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 0; background-color: #f0f2f5; color: #1f2937; }}
        .navbar {{ background-color: #374151; padding: 10px 20px; color: white; display: flex; justify-content: space-between; align-items: center; }}
        .navbar a {{ color: white; text-decoration: none; margin-right: 15px; }} .navbar .repo-name {{ font-weight: 600; }}
        .container {{ max-width: 1200px; margin: 20px auto; padding: 20px; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        h1 {{ color: #111827; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5em; margin-bottom: 1em; font-size: 1.8em; }}
        select {{ padding: 10px; margin-bottom: 10px; border-radius: 6px; border: 1px solid #d1d5db; background-color: #f9fafb; width: 100%; max-width: 500px; box-sizing: border-box; }}
        #content-display-area {{ margin-top: 10px; border-radius: 6px; overflow: hidden; }}
        pre.text-content-pre {{ white-space: pre-wrap; word-wrap: break-word; background: #f9fafb; border: 1px solid #e5e7eb; padding: 15px; border-radius: 6px; font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, Courier, monospace; font-size: 0.875em; line-height: 1.6; overflow-x: auto;}}
        .pr-link-container, .pr-details-link-container {{ margin-bottom: 20px; font-size: 0.9em; }}
        .pr-link-container a, .pr-details-link-container a {{ color: #2563eb; text-decoration: none; }} .pr-link-container a:hover, .pr-details-link-container a:hover {{ text-decoration: underline; }}
        .status-message {{ padding: 10px; border-radius: 6px; margin-bottom: 15px; background-color: #eff6ff; color: #1e40af; border: 1px solid #bfdbfe; }}
        .added-line {{ background-color: #e6ffed; /* General added line */ }}
        .pr-annotated {{ 
            cursor: help; 
        }}
        .pr-annotated:hover {{ background-color: #c3f7c3; }}
        .pr-section-for-file {{ margin-bottom: 2em; padding-bottom: 1em; border-bottom: 1px solid #ccc; }}
        .pr-section-for-file:last-child {{ border-bottom: none; }}
        .pr-section-for-file h3 {{ font-size: 1.1em; margin-bottom: 0.5em; }}
        .diff-view-item {{ border: 1px solid #e0e0e0; border-radius: 4px; margin-top: 0.5em; }}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
    <div class="navbar">
        <a href="{index_rel_path}">🏠 Back to Repository Index</a>
        <span class="repo-name">{html.escape(owner)}/{html.escape(repo)}</span>
    </div>
    <div class="container">
        <h1>{file_path_display}</h1>
        <label for="pr-selector" style="display:block; margin-bottom: 5px; font-weight: 500;">View mode:</label>
        <select id="pr-selector">{pr_options_html}</select>
        <div id="selected-pr-link-container" class="pr-link-container"></div>
        <div id="pr-details-link-container" class="pr-details-link-container"></div>
        <div id="content-display-area">
            {'<pre id="text-content-display" class="text-content-pre"></pre>'}
        </div>
    </div>
    <script type="text/javascript" src="{assets_rel_path}/diff2html-ui.min.js"></script>
    <script>
        const baseFileContentHTML = `{base_content_html_escaped}`; 
        const prDataForFile = {json.dumps(js_pr_data)};
        const allPrsInterleavedLineData = {all_prs_interleaved_lines_json}; 
        const fileNameForDiff = "{html.escape(file_info['name'])}"; 

        const contentDisplayArea = document.getElementById('content-display-area');
        const textContentDisplayElement = document.getElementById('text-content-display'); 
        const prSelector = document.getElementById('pr-selector');
        const selectedPrLinkContainer = document.getElementById('selected-pr-link-container');
        const prDetailsLinkContainer = document.getElementById('pr-details-link-container');

        function displayHtmlInPre(htmlString) {{
            if (textContentDisplayElement) {{ 
                 textContentDisplayElement.innerHTML = htmlString; 
            }} else {{ 
                contentDisplayArea.innerHTML = `<pre class="text-content-pre">${{htmlString}}</pre>`;
            }}
        }}

        function clearDynamicContent() {{
            selectedPrLinkContainer.innerHTML = ''; 
            prDetailsLinkContainer.innerHTML = '';
        }}

        function displayBaseContent() {{
            clearDynamicContent();
            contentDisplayArea.innerHTML = ''; 
            if (textContentDisplayElement) {{ 
                 contentDisplayArea.appendChild(textContentDisplayElement);
            }}
            displayHtmlInPre(baseFileContentHTML); 
        }}

        function displayPRChanges(prNumberStr) {{ 
            clearDynamicContent();
            const currentPRData = prDataForFile[prNumberStr];
            contentDisplayArea.innerHTML = ''; 
            if (textContentDisplayElement) {{
                contentDisplayArea.appendChild(textContentDisplayElement);
            }}

            if (currentPRData && currentPRData.merged_content_html !== undefined && currentPRData.merged_content_html !== null) {{
                displayHtmlInPre(currentPRData.merged_content_html); 
                if (currentPRData.html_url) {{
                    selectedPrLinkContainer.innerHTML = `<a href="${{currentPRData.html_url}}" target="_blank" title="View PR on GitHub">🔗 View PR #${{prNumberStr}} on GitHub</a>`;
                }}
            }} else {{ 
                 displayHtmlInPre("Merged content for PR #" + prNumberStr + " is not available (file might be binary, or patch application failed).");
            }}
            if (currentPRData && currentPRData.local_pr_page_link) {{
                prDetailsLinkContainer.innerHTML = `<a href="${{currentPRData.local_pr_page_link}}" title="View all changes in this PR locally">📖 View all changes in PR #${{prNumberStr}} on local site</a>`;
            }}
        }}

        function displayAllPRChangesInterleaved() {{ 
            clearDynamicContent();
            contentDisplayArea.innerHTML = ''; 

            let finalHtml = "";
            if (allPrsInterleavedLineData && allPrsInterleavedLineData.length > 0) {{
                allPrsInterleavedLineData.forEach(lineObj => {{
                    if (lineObj.type === 'added' && lineObj.pr_info) {{
                        // Python side already HTML escapes lineObj.text and pr_info.title
                        finalHtml += `<span class="added-line pr-annotated" title="PR #${{lineObj.pr_info.number}}: ${{lineObj.pr_info.title}}">${{lineObj.text}}</span>\\n`;
                    }} else {{
                        finalHtml += lineObj.text + '\\n'; // lineObj.text is already HTML escaped
                    }}
                }});
            }} else {{
                finalHtml = "No changes from relevant PRs to display in interleaved view, or an error occurred generating it.";
            }}

            const newPre = document.createElement('pre');
            newPre.className = 'text-content-pre';
            newPre.innerHTML = finalHtml.trim(); 
            contentDisplayArea.appendChild(newPre);
        }}


        prSelector.addEventListener('change', function() {{
            if (this.value === 'base_content') {{
                displayBaseContent();
            }} else if (this.value === 'all_pr_changes_interleaved') {{ 
                displayAllPRChangesInterleaved();
            }} else if (prDataForFile[this.value]) {{
                displayPRChanges(this.value); 
            }}
        }});
        displayBaseContent(); 
    </script>
</body></html>"""
    os.makedirs(os.path.dirname(html_file_path_abs), exist_ok=True)
    with open(html_file_path_abs, 'w', encoding='utf-8') as f:
        f.write(html_template)


def generate_repo_index_html(owner, repo, repo_files_metadata, pr_list_details, html_output_dir_abs, assets_rel_path,
                             pulls_dir_rel_path):
    files_html_list = "<ul>"
    sorted_files_metadata = sorted(repo_files_metadata,
                                   key=lambda x: (0 if x['type'] == 'dir' else 1, x['name'].lower()))
    for f_info in sorted_files_metadata:
        icon = "&#128193;" if f_info['type'] == 'dir' else "&#128196;"
        link_target = f_info["html_link"] if f_info['type'] == 'file' else "#"
        link_class = "file-link" if f_info['type'] == 'file' else "dir-link"
        link = f'<a href="{link_target}" class="{link_class}">{html.escape(f_info["name"])}</a>'
        files_html_list += f'<li><span class="icon">{icon}</span> {link} <span class="path-hint">({html.escape(f_info["path"])})</span></li>'
    files_html_list += "</ul>"
    prs_html_list = "<ul>"
    if pr_list_details:
        for pr_info in pr_list_details:
            user_login = html.escape(pr_info.get('user', {}).get('login', 'N/A'))
            pr_title_escaped = html.escape(pr_info["title"])
            local_pr_page_link = os.path.join(pulls_dir_rel_path, f"{pr_info['number']}.html").replace("\\", "/")
            prs_html_list += f'<li><a href="{local_pr_page_link}" title="View PR #{pr_info["number"]} details locally">#{pr_info["number"]}: {pr_title_escaped}</a> (by {user_login}) <a href="{pr_info["html_url"]}" target="_blank" class="github-link" title="View on GitHub">(GH)</a></li>'
    else:
        prs_html_list = "<p>No open pull requests found or loaded.</p>"
    prs_html_list += "</ul>"
    index_html_content = f"""
<!DOCTYPE html><html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Repository: {owner}/{repo}</title>
    <style>
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 0; background-color: #f0f2f5; color: #1f2937; }}
        .navbar {{ background-color: #374151; padding: 10px 20px; color: white; font-size: 1.1em; display: flex; justify-content: space-between; align-items: center;}}
        .navbar strong {{ font-weight: 600; }} .navbar .repo-name {{ font-weight: normal; }}
        .container {{ max-width: 1000px; margin: 20px auto; padding: 20px; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        h1, h2 {{ color: #111827; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5em; margin-bottom: 1em;}}
        h1 {{ font-size: 2em; text-align: center; }} h2 {{ font-size: 1.5em; }}
        ul {{ list-style-type: none; padding-left: 0; }}
        li {{ margin-bottom: 10px; padding: 8px; border-radius: 4px; transition: background-color 0.2s; }}
        li:hover {{ background-color: #f3f4f6; }}
        a {{ color: #2563eb; text-decoration: none; font-weight: 500; }} a:hover {{ text-decoration: underline; color: #1d4ed8; }}
        .icon {{ margin-right: 8px; font-size: 1.1em; }} .path-hint {{ font-size: 0.8em; color: #6b7280; margin-left: 10px; }}
        .dir-link {{ color: #374151; font-weight: 500; cursor: default; }} 
        .github-link {{ font-size: 0.8em; color: #4b5563; margin-left: 5px; }}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
    <div class="navbar"><strong>GitHub Local Viewer</strong><span class="repo-name">{html.escape(owner)} / {html.escape(repo)}</span></div>
    <div class="container">
        <h1>Repository Overview</h1>
        <section id="files-section"><h2>Files and Directories</h2>{files_html_list}</section>
        <section id="prs-section"><h2>Open Pull Requests</h2>{prs_html_list}</section>
    </div>
</body></html>"""
    with open(os.path.join(html_output_dir_abs, "index.html"), 'w', encoding='utf-8') as f:
        f.write(index_html_content)


def generate_pr_html_page(owner, repo, pr_info, html_pr_page_path_abs, assets_rel_path, files_dir_rel_path):
    pr_number = pr_info['number'];
    pr_title_escaped = html.escape(pr_info['title'])
    pr_author = html.escape(pr_info.get('user', {}).get('login', 'N/A'))
    pr_body_html = html.escape(pr_info.get('body') or "No description provided.").replace("\r\n", "<br>\n").replace(
        "\n", "<br>\n")
    files_changed_html_content = "";
    file_patches_for_javascript = []
    if not pr_info.get('files_changed'):
        files_changed_html_content = "<p>No file change data for this PR.</p>"
    else:
        for i, item in enumerate(pr_info['files_changed']):
            fname_esc = html.escape(item['filename']);
            patch_ok = 'patch' in item and item['patch'] is not None
            status_esc = html.escape(item.get('status', 'N/A'))
            local_file_link = os.path.join(files_dir_rel_path, item['filename'] + ".html").replace("\\", "/")
            diff_id = f"diff-output-{i}"
            files_changed_html_content += f"""<div class="file-change-item"><h3><a href="{local_file_link}" title="View base file">{fname_esc}</a> <span class="file-status">({status_esc})</span></h3>"""
            if patch_ok:
                files_changed_html_content += f'<div id="{diff_id}" class="diff-view"></div>'
                file_patches_for_javascript.append({"id_suffix_for_div": i, "patch": item['patch']})
            else:
                files_changed_html_content += "<p class='no-patch-message'>No textual patch (e.g., binary, renamed).</p>"
            files_changed_html_content += "</div>"
    pr_page_dir_abs = os.path.dirname(html_pr_page_path_abs)
    html_output_dir_abs = os.path.abspath(os.path.join(pr_page_dir_abs, ".."))
    index_rel_path = os.path.relpath(os.path.join(html_output_dir_abs, "index.html"), pr_page_dir_abs).replace("\\",
                                                                                                               "/")
    html_template = f"""
<!DOCTYPE html><html lang="en">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PR #{pr_number}: {pr_title_escaped} - {owner}/{repo}</title>
    <link rel="stylesheet" type="text/css" href="{assets_rel_path}/diff2html.min.css">
    <style>
        body {{ font-family: 'Inter', sans-serif; margin: 0; padding: 0; background-color: #f0f2f5; color: #1f2937; }}
        .navbar {{ background-color: #374151; padding: 10px 20px; color: white; display: flex; justify-content: space-between; align-items: center; }}
        .navbar a {{ color: white; text-decoration: none; margin-right: 15px; }} .navbar .repo-name {{ font-weight: 600; }}
        .container {{ max-width: 1200px; margin: 20px auto; padding: 20px; background-color: #ffffff; border-radius: 8px; box-shadow: 0 2px 10px rgba(0,0,0,0.05); }}
        h1, h2, h3 {{ color: #111827; }}
        h1 {{ border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5em; margin-bottom: 0.5em; font-size: 1.8em; }}
        .pr-meta {{ font-size: 0.9em; color: #4b5563; margin-bottom: 1.5em; }} .pr-meta strong {{ color: #1f2937; }} .pr-meta a {{ color: #2563eb; }}
        .pr-body {{ background-color: #f9fafb; border: 1px solid #e5e7eb; padding: 15px; border-radius: 6px; margin-bottom: 2em; white-space: pre-wrap; word-wrap: break-word; line-height: 1.6; }}
        h2 {{ font-size: 1.5em; border-bottom: 1px solid #e5e7eb; padding-bottom: 0.5em; margin-bottom: 1em; }}
        .file-change-item {{ margin-bottom: 2em; padding-bottom: 1.5em; border-bottom: 1px dashed #d1d5db; }} .file-change-item:last-child {{ border-bottom: none; }}
        .file-change-item h3 {{ font-size: 1.2em; margin-bottom: 0.5em; }} .file-change-item h3 a {{ color: #111827; }}
        .file-status {{ font-size: 0.8em; color: #6b7280; font-weight: normal; margin-left: 5px; }}
        .diff-view {{ border: 1px solid #e5e7eb; border-radius: 6px; overflow: hidden; margin-top: 0.5em; }}
        .d2h-file-header {{ display: none !important; }} .no-patch-message {{ font-style: italic; color: #6b7280; background-color: #f9fafb; padding: 10px; border-radius: 4px; border: 1px dashed #e5e7eb;}}
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
</head>
<body>
    <div class="navbar"><a href="{index_rel_path}">🏠 Back to Index</a><span class="repo-name">{html.escape(owner)}/{html.escape(repo)}</span></div>
    <div class="container">
        <h1>PR #{pr_number}: {pr_title_escaped}</h1>
        <div class="pr-meta">Opened by <strong>{pr_author}</strong> | <a href="{pr_info['html_url']}" target="_blank" title="View on GitHub">View on GitHub 🔗</a></div>
        <div class="pr-body">{pr_body_html}</div>
        <h2>Files Changed ({len(pr_info.get('files_changed', []))})</h2>
        <div id="files-changed-list">{files_changed_html_content}</div>
    </div>
    <script type="text/javascript" src="{assets_rel_path}/diff2html-ui.min.js"></script>
    <script>
        const filePatches = {json.dumps(file_patches_for_javascript)};
        filePatches.forEach(fileData => {{
            const targetElement = document.getElementById(`diff-output-${{fileData.id_suffix_for_div}}`);
            if (targetElement && fileData.patch) {{
                const diff2htmlUi = new Diff2HtmlUI(targetElement);
                diff2htmlUi.draw(fileData.patch, {{ inputFormat: 'diff', showFiles: false, matching: 'lines', outputFormat: 'side-by-side', drawFileList: false }});
            }}
        }});
    </script>
</body></html>"""
    with open(html_pr_page_path_abs, 'w', encoding='utf-8') as f:
        f.write(html_template)


# --- New Python function for generating interleaved view data ---
def generate_interleaved_lines_for_all_prs(base_content_str, relevant_prs_data):  # Removed unused 3rd param
    """
    Attempts to create a single list of line objects representing the base content
    with additions from all relevant PRs interleaved and annotated.
    This is a best-effort visualization, not a true sequential merge.
    Returns a list of dicts: [{'text': '...', 'type': 'base'/'added', 'pr_info': pr_details_or_None}]
    """
    if base_content_str is None: base_content_str = ""
    base_lines = base_content_str.splitlines()

    interleaved_lines = [{'text': html.escape(line), 'type': 'base', 'pr_info': None} for line in base_lines]
    additions_map = {}

    sorted_pr_numbers = sorted(relevant_prs_data.keys(), key=lambda x: int(x))

    for pr_num_str in sorted_pr_numbers:
        pr_data = relevant_prs_data[pr_num_str]
        patch_string = pr_data.get("patch")
        if not patch_string:
            continue

        pr_details = {
            'number': pr_num_str,
            'title': html.escape(pr_data.get('title', 'Unknown PR')),  # Title is already escaped if from user input
            'html_url': pr_data.get('html_url', '#'),
            'local_pr_page_link': pr_data.get('local_pr_page_link', '#')  # This is now part of pr_data
        }

        raw_patch_lines = patch_string.splitlines()
        current_hunk_header = None
        current_hunk_body = []

        hunk_sections = []
        for line in raw_patch_lines:
            if line.startswith("@@"):
                if current_hunk_header: hunk_sections.append((current_hunk_header, current_hunk_body))
                current_hunk_header = line;
                current_hunk_body = []
            elif current_hunk_header:
                if line.startswith(("+", "-", " ", "\\")): current_hunk_body.append(line)
        if current_hunk_header: hunk_sections.append((current_hunk_header, current_hunk_body))

        for header, body in hunk_sections:
            match = re.search(r"@@ -(\d+)(,(\d+))? \+(\d+)(,(\d+))? @@", header)
            if not match: continue

            old_start_1based = int(match.group(1))
            target_insertion_line_0_idx = old_start_1based - 1 if old_start_1based > 0 else -1
            temp_base_line_offset_in_hunk = 0
            for hunk_line in body:
                if hunk_line.startswith("+"):
                    line_content = html.escape(hunk_line[1:])
                    line_obj = {'text': line_content, 'type': 'added', 'pr_info': pr_details}
                    insertion_key = target_insertion_line_0_idx + temp_base_line_offset_in_hunk
                    if insertion_key not in additions_map:
                        additions_map[insertion_key] = []
                    additions_map[insertion_key].append(line_obj)
                elif hunk_line.startswith("-"):
                    temp_base_line_offset_in_hunk += 1
                elif hunk_line.startswith(" "):
                    temp_base_line_offset_in_hunk += 1

    final_lines_with_objects = []
    if -1 in additions_map:
        for added_line_obj in additions_map[-1]:
            final_lines_with_objects.append(added_line_obj)

    for i, base_line_text in enumerate(base_lines):
        final_lines_with_objects.append({'text': html.escape(base_line_text), 'type': 'base', 'pr_info': None})
        if i in additions_map:
            for added_line_obj in additions_map[i]:
                final_lines_with_objects.append(added_line_obj)

    return final_lines_with_objects


# --- Main Processing Logic ---
def process_repository(owner, repo):
    start_time = time.time()
    print(f"\nProcessing repository: {owner}/{repo}")
    repo_output_base_dir = os.path.join(OUTPUT_BASE_DIR, owner, repo)
    html_output_dir_abs = os.path.join(repo_output_base_dir, "html")
    html_files_sub_dir_abs = os.path.join(html_output_dir_abs, "files")
    html_pulls_sub_dir_abs = os.path.join(html_output_dir_abs, "pulls")
    assets_dir_abs = os.path.join(html_output_dir_abs, "assets")
    os.makedirs(html_files_sub_dir_abs, exist_ok=True)
    os.makedirs(html_pulls_sub_dir_abs, exist_ok=True)
    os.makedirs(assets_dir_abs, exist_ok=True)
    if not ensure_assets(assets_dir_abs): print("Error: Assets download failed. Aborting."); return
    api = GitHubAPI(owner, repo)

    print("Step 1: Fetching repository file structure and content...")
    all_repo_files_metadata_for_index = []
    all_files_content_details_for_pages = {}

    def fetch_all_repository_items(current_dir_path=''):
        items_in_dir = api.get_repo_contents(current_dir_path)
        if not items_in_dir: return
        for item in items_in_dir:
            item_full_path = item['path']
            if item['type'] == 'file':
                file_html_page_link_rel = os.path.join("files", item_full_path + ".html").replace("\\", "/")
                all_repo_files_metadata_for_index.append(
                    {'name': item['name'], 'path': item_full_path, 'type': 'file', 'sha': item['sha'],
                     'size': item.get('size', 0), 'html_link': file_html_page_link_rel})
                if item_full_path not in all_files_content_details_for_pages:
                    file_content_bytes = api.get_file_blob_content(item['sha'])
                    content_str, is_binary = None, True
                    is_too_large = item.get('size', 0) > MAX_FILE_SIZE_FOR_CONTENT_DISPLAY
                    if file_content_bytes:
                        try:
                            content_str, is_binary = file_content_bytes.decode('utf-8'), False
                        except UnicodeDecodeError:
                            content_str = f"[Binary content of size {len(file_content_bytes)} bytes]"
                    all_files_content_details_for_pages[item_full_path] = {'content_str': content_str,
                                                                           'is_binary': is_binary,
                                                                           'is_too_large': is_too_large,
                                                                           'sha': item['sha'],
                                                                           'size': item.get('size', 0),
                                                                           'name': item['name']}
            elif item['type'] == 'dir':
                all_repo_files_metadata_for_index.append(
                    {'name': item['name'], 'path': item_full_path, 'type': 'dir', 'html_link': "#"})
                fetch_all_repository_items(item_full_path)

    fetch_all_repository_items()

    print("\nStep 2: Fetching pull requests information...")
    pull_requests_metadata_list = api.get_pull_requests(state='open')
    all_pr_details_with_files = {}
    if pull_requests_metadata_list:
        print(f"  Found {len(pull_requests_metadata_list)} open PRs. Fetching file details for each...")
        for pr_meta in pull_requests_metadata_list:
            pr_number = pr_meta['number']
            pr_files_changed_data = api.get_pull_request_files(pr_number)
            all_pr_details_with_files[pr_number] = {'number': pr_number, 'title': pr_meta['title'],
                                                    'html_url': pr_meta['html_url'], 'user': pr_meta.get('user'),
                                                    'body': pr_meta.get('body'),
                                                    'files_changed': pr_files_changed_data if pr_files_changed_data else []}
    else:
        print("  No open pull requests found or an error occurred.")

    print("\nStep 3: Generating repository index.html...")
    assets_rel_path_for_index = os.path.relpath(assets_dir_abs, html_output_dir_abs).replace("\\", "/")
    pulls_dir_rel_path_for_index = os.path.relpath(html_pulls_sub_dir_abs, html_output_dir_abs).replace("\\", "/")
    generate_repo_index_html(owner, repo, all_repo_files_metadata_for_index, list(all_pr_details_with_files.values()),
                             html_output_dir_abs, assets_rel_path_for_index, pulls_dir_rel_path_for_index)

    print("\nStep 4: Generating HTML pages for individual files...")
    for file_full_path, file_content_detail in all_files_content_details_for_pages.items():
        output_html_file_abs_path = os.path.join(html_files_sub_dir_abs, file_full_path + ".html")
        output_html_file_dir_abs = os.path.dirname(output_html_file_abs_path)
        assets_rel_path_for_file_page = os.path.relpath(assets_dir_abs, output_html_file_dir_abs).replace("\\", "/")
        pulls_dir_rel_path_for_file_page = os.path.relpath(html_pulls_sub_dir_abs, output_html_file_dir_abs).replace(
            "\\", "/")

        relevant_prs_info_for_file = {}
        all_prs_patches_for_interleaved_view = {}

        for pr_num, pr_detail_data in all_pr_details_with_files.items():
            for pr_file_change_info in pr_detail_data.get('files_changed', []):
                if pr_file_change_info['filename'] == file_full_path and 'patch' in pr_file_change_info:
                    merged_content_html = None
                    pr_annotation_details = {
                        'number': pr_num,
                        'title': pr_detail_data['title'],
                        'gh_link': pr_detail_data['html_url'],
                        'local_link': os.path.join(pulls_dir_rel_path_for_file_page, f"{pr_num}.html").replace("\\",
                                                                                                               "/")
                    }
                    if not file_content_detail['is_binary'] and file_content_detail['content_str'] is not None and \
                            pr_file_change_info['patch'] is not None:
                        try:
                            merged_content_html = apply_patch_to_content(
                                file_content_detail['content_str'],
                                pr_file_change_info['patch'],
                                pr_annotation_details
                            )
                        except Exception as e:
                            print(f"Error applying single patch for PR #{pr_num} to file {file_full_path}: {e}")
                            merged_content_html = html.escape(f"[Error applying patch: {e}]")

                    relevant_prs_info_for_file[pr_num] = {
                        'title': pr_detail_data['title'],
                        'html_url': pr_detail_data['html_url'],
                        'patch_for_this_file': pr_file_change_info['patch'],
                        'merged_content_html_for_this_file': merged_content_html
                    }
                    all_prs_patches_for_interleaved_view[str(pr_num)] = {
                        "patch": pr_file_change_info['patch'],
                        "title": pr_detail_data['title'],
                        "html_url": pr_detail_data['html_url'],
                        "local_pr_page_link": os.path.join(pulls_dir_rel_path_for_file_page, f"{pr_num}.html").replace(
                            "\\", "/")
                    }
                    break

        interleaved_lines_data = []
        if not file_content_detail['is_binary'] and file_content_detail['content_str'] is not None:
            try:
                interleaved_lines_data = generate_interleaved_lines_for_all_prs(
                    file_content_detail['content_str'],
                    all_prs_patches_for_interleaved_view
                )
            except Exception as e:
                print(f"Error generating interleaved view for {file_full_path}: {e}")
                interleaved_lines_data = [
                    {'text': html.escape(f"[Error generating interleaved view: {e}]"), 'type': 'base', 'pr_info': None}]

        file_info_for_page_template = {'path': file_full_path, 'name': file_content_detail['name'],
                                       'size': file_content_detail['size']}
        generate_file_html_page(
            owner, repo, file_info_for_page_template,
            file_content_detail['content_str'], file_content_detail['is_binary'], file_content_detail['is_too_large'],
            relevant_prs_info_for_file, output_html_file_abs_path,
            assets_rel_path_for_file_page, pulls_dir_rel_path_for_file_page,
            json.dumps(interleaved_lines_data)
        )

    print("\nStep 5: Generating HTML pages for Pull Requests...")
    if all_pr_details_with_files:
        for pr_number_key, pr_detail_data_complete in all_pr_details_with_files.items():
            html_pr_page_abs_path = os.path.join(html_pulls_sub_dir_abs, f"{pr_number_key}.html")
            pr_page_dir_abs = os.path.dirname(html_pr_page_abs_path)
            assets_rel_path_for_pr_page = os.path.relpath(assets_dir_abs, pr_page_dir_abs).replace("\\", "/")
            files_dir_rel_path_for_pr_page = os.path.relpath(html_files_sub_dir_abs, pr_page_dir_abs).replace("\\", "/")
            generate_pr_html_page(owner, repo, pr_detail_data_complete, html_pr_page_abs_path,
                                  assets_rel_path_for_pr_page, files_dir_rel_path_for_pr_page)
    else:
        print("  No Pull Requests to generate pages for.")

    end_time = time.time()
    print(f"\nSuccessfully generated static site for {owner}/{repo}!")
    print(f"Output directory: {html_output_dir_abs}")
    print(f"Total processing time: {end_time - start_time:.2f} seconds.")
    print(f"API Rate Limit: {api.rate_limit_remaining if api.rate_limit_remaining is not None else 'N/A'} remaining.")


# --- Script Entry Point ---
if __name__ == "__main__":
    print("GitHub Local Repository Viewer Generator")
    print("--------------------------------------")
    default_owner = "psf";
    default_repo = "requests"
    try:
        repo_owner_input = input(f"Enter repository owner (e.g., '{default_owner}'): ").strip() or default_owner
        repo_name_input = input(f"Enter repository name (e.g., '{default_repo}'): ").strip() or default_repo
    except KeyboardInterrupt:
        print("\nOperation cancelled by user."); exit(0)
    if not repo_owner_input or not repo_name_input:
        print("Error: Repository owner and name cannot be empty.")
    else:
        try:
            process_repository(repo_owner_input, repo_name_input)
            final_index_path = os.path.abspath(
                os.path.join(OUTPUT_BASE_DIR, repo_owner_input, repo_name_input, 'html', 'index.html'))
            print(f"\nTo view the generated site, open this file in your web browser:\nfile://{final_index_path}")
        except KeyboardInterrupt:
            print("\nProcessing interrupted by user.")
        except Exception as e:
            print(f"\nAn unexpected error occurred during processing: {e}")
            import traceback;

            traceback.print_exc()
