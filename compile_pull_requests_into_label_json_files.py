"""
Create json files for pull request conversation and file changes for PR labels

Usage:
  compile_pull_requests_into_label_json_files.py <base_PR_json> <output_folder> <owner> <repo>
  compile_pull_requests_into_label_json_files.py -h | --help

  <base_PR_json>: retrieved repo's pulls_meta json file path
  <base_folder>: folder where previously retrieved pull requests are stored and where consolidated files are to be created
  <owner>: GitHub Repo owner
  <repo>: GitHub Repo

Examples:
  compile_pull_requests_into_label_json_files.py YWxs.json "./gh_output" team-mirai policy

Options:
  -h --help     Show this screen.
  --version     Show version.
"""
import json
import os
from docopt import docopt

def process_pull_request_files():
    """
    Reads pull request metadata from individual JSON files and a summary file,
    extracts relevant information (url, body, filename, added lines from patch),
    and categorizes/saves processed data into multiple JSON files based on PR labels.
    """

    arguments = docopt(__doc__, version="0.1")
    PULLS_META_SUMMARY_FILE = arguments["<base_PR_json>"]  #"YWxs.json"
    OUTPUT_BASE_DIR = arguments["<output_folder>"]         # "./gh_output"
    owner = arguments["<owner>"]                           #"team-mirai"
    repo = arguments["<repo>"]                             # "policy"
    print(f"\nProcessing repository: {owner}/{repo}")

    # Define the directory where pull request summary file is located
    pulls_meta_dir = os.path.join(OUTPUT_BASE_DIR, owner, repo, '_cache', 'pulls_meta')
    # Define the directory where individual pull request detail files are located
    pr_detail_files_dir = os.path.join(OUTPUT_BASE_DIR, owner, repo, '_cache', 'pull_files_detail')
    # Define the directory where processed output will be saved
    processed_pulls_dir = os.path.join(OUTPUT_BASE_DIR, owner, repo, '_cache', 'consolidated_json')

    # Create output directories if they don't exist
    os.makedirs(processed_pulls_dir, exist_ok=True)
    os.makedirs(pr_detail_files_dir, exist_ok=True) # Ensure the new detail directory exists

    # Check if the input directories exist
    if not os.path.exists(pulls_meta_dir):
        print(f"Error: PR summary directory not found at {pulls_meta_dir}")
        return
    if not os.path.exists(pr_detail_files_dir):
        print(f"Error: PR detail files directory not found at {pr_detail_files_dir}")
        return


    # --- Step 1: Load PR Summaries (url, body, labels) from the designated summary file ---
    pr_summaries_map = {}
    pulls_meta_summary_file_path = os.path.join(pulls_meta_dir, PULLS_META_SUMMARY_FILE)

    try:
        with open(pulls_meta_summary_file_path, 'r', encoding='utf-8') as f:
            json_meta_summary = json.load(f)
            if isinstance(json_meta_summary, list):
                for item in json_meta_summary:
                    # Assuming 'number' key exists in the summary for PR number
                    pr_number = item.get('number')
                    if pr_number is not None:
                        try:
                            # Extract label names
                            labels = [label.get('name') for label in item.get('labels', []) if label.get('name')]
                            pr_summaries_map[int(pr_number)] = {
                                'url': item.get('url', ''),
                                'title': item.get('title', ''),
                                'body': item.get('body', ''),
                                'labels': labels # Store the extracted label names
                            }
                        except ValueError:
                            print(f"Warning: Could not convert PR number '{pr_number}' to integer in {PULLS_META_SUMMARY_FILE}. Skipping this entry.")
                        except Exception as e:
                            print(f"Warning: Error processing labels for PR {pr_number} in {PULLS_META_SUMMARY_FILE}: {e}")
            else:
                print(f"Warning: {PULLS_META_SUMMARY_FILE} is not a list of PR summaries. 'url', 'body', and 'labels' fields might be missing in output.")
    except FileNotFoundError:
        print(f"Warning: PR summary file not found at {pulls_meta_summary_file_path}. 'url', 'body', and 'labels' fields will be empty for all PRs.")
    except json.JSONDecodeError:
        print(f"Error: Could not decode JSON from {pulls_meta_summary_file_path}. Skipping PR summaries.")
    except Exception as e:
        print(f"An unexpected error occurred while loading PR summaries from {PULLS_META_SUMMARY_FILE}: {e}")

    # This dictionary will store PRs categorized by their labels
    # Key: label name (string), Value: list of processed PR entries
    categorized_prs = {}

    # --- Step 2: Iterate and Process Detailed PR Files from the new directory ---
    for file_name in os.listdir(pr_detail_files_dir):
        # Process only JSON files that look like pull request numbers (e.g., '123.json')
        if file_name.endswith('.json') and file_name[:-5].isdigit():
            input_file_path = os.path.join(pr_detail_files_dir, file_name)
            pr_number_str = file_name[:-5]
            pr_number = int(pr_number_str)

            print(f"Processing pull request detail file: {file_name}")

            try:
                # Open and read the source JSON file, ensuring UTF-8 encoding
                with open(input_file_path, 'r', encoding='utf-8') as f:
                    pr_meta_data = json.load(f)

                # Get the URL, body, and labels for this PR from the summary map
                pr_info = pr_summaries_map.get(pr_number, {'url': '', 'body': '', 'labels': []})
                pr_url = pr_info['url']
                pr_title = pr_info['title']
                pr_body = pr_info['body']
                pr_labels = pr_info['labels'] # Get the labels for this PR

                # This list will store the extracted filename and added lines for the current PR's file changes
                file_changes_list = []

                # Iterate through each item (representing a file change) in the PR's metadata
                for item in pr_meta_data:
                    filename = item.get('filename')
                    patch = item.get('patch')
                    added_lines = []

                    if patch:
                        # Split the patch into individual lines
                        lines = patch.split('\n')
                        for line in lines:
                            # Check if the line starts with '+' and is not a '+++' header line
                            if line.startswith('+') and not line.startswith('+++'):
                                # Add the line, removing the leading '+' character
                                added_lines.append(line[1:])

                    # Append the processed data for this file change
                    file_changes_list.append({
                        "filename": filename,
                        "added_lines": added_lines
                    })

                # Construct the entry for the current pull request
                processed_pr_entry = {
                    "pr_number": pr_number,
                    "url": pr_url,
                    "title": pr_title,
                    "body": pr_body,
                    "file_changes": file_changes_list
                }

                # Categorize the processed PR entry by its labels
                if pr_labels:
                    for label_name in pr_labels:
                        if label_name not in categorized_prs:
                            categorized_prs[label_name] = []
                        categorized_prs[label_name].append(processed_pr_entry)
                else:
                    # If no labels, add to 'no_label' category
                    if 'no_label' not in categorized_prs:
                        categorized_prs['no_label'] = []
                    categorized_prs['no_label'].append(processed_pr_entry)

                print(f"  Successfully processed PR {pr_number_str} with labels: {pr_labels if pr_labels else 'No labels'}.")

            except json.JSONDecodeError:
                print(f"Error: Could not decode JSON from {input_file_path}. The file might be corrupted or not valid JSON.")
            except Exception as e:
                print(f"An unexpected error occurred while processing {file_name}: {e}")
        elif file_name.endswith('.json'):
            print(f"Skipping non-PR-number JSON file in {pr_detail_files_dir}: {file_name}")

    # --- Step 3: Save All Categorized Data to Separate Output Files ---
    print("\nSaving categorized PR data to separate files...")
    for label_name, pr_list in categorized_prs.items():
        # Sanitize label name for use as a filename (replace problematic characters)
        # For simplicity, replacing non-alphanumeric with underscore.
        # More robust sanitization might be needed depending on actual label names.
        safe_label_name = "".join(c if c.isalnum() else "_" for c in label_name)
        output_file_name = f"{safe_label_name}.json"
        output_file_path = os.path.join(processed_pulls_dir, output_file_name)

        try:
            with open(output_file_path, 'w', encoding='utf-8') as f:
                json.dump(pr_list, f, ensure_ascii=False, indent=2)
            print(f"  Saved {len(pr_list)} PRs to: {output_file_name}")
        except Exception as e:
            print(f"An error occurred while writing the output file for label '{label_name}': {e}")


# --- Script Entry Point ---
if __name__ == "__main__":
    print("Merge PR conversation and changes according to label categories")
    process_pull_request_files()

