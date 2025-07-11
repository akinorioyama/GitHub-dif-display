import json
import sys
import os
from collections import defaultdict
from datetime import datetime
import pytz # Import the pytz library

def process_github_data(json_data):
    """
    Processes a list of GitHub pull request data to generate reports.

    Args:
        json_data (str): A string containing the JSON data of pull requests.

    Returns:
        None. Prints the formatted tables directly.
    """
    try:
        # Load the JSON string into a Python list of dictionaries
        pull_requests = json.loads(json_data)
    except json.JSONDecodeError:
        print("Error: The file content is not valid JSON. Please check the file.")
        return

    # A dictionary to hold the count of PRs per date.
    date_counts = defaultdict(int)

    # A list to store individual PR numbers and their creation dates.
    pr_list = []

    # Define the Japan Standard Timezone (JST)
    jst_timezone = pytz.timezone('Asia/Tokyo')

    for pr in pull_requests:
        pr_number = pr.get("number")
        created_at_str = pr.get("created_at")

        if not pr_number or not created_at_str:
            continue

        # Convert the ISO 8601 timestamp string to a datetime object
        dt_object = datetime.fromisoformat(created_at_str.replace('Z', '+00:00'))

        # Convert the UTC datetime object to Japan Standard Time (JST)
        dt_object_jst = dt_object.astimezone(jst_timezone)

        # Format the date into 'YYYY-MM-DD'
        formatted_date = dt_object_jst.strftime('%Y-%m-%d')

        # Increment the count for this date
        date_counts[formatted_date] += 1

        # Add the PR number and formatted date to our list
        pr_list.append({"number": pr_number, "date": formatted_date})

    # --- Print the Summary Table ---
    print("Summary of Items by Date")
    print("+------------+-----------------+")
    print("| Date       | Number of Items |")
    print("+------------+-----------------+")

    sorted_dates = sorted(date_counts.keys())

    if not sorted_dates:
        print("| No data available         |")
    else:
        for date in sorted_dates:
            count = date_counts[date]
            print(f"| {date} | {count:<15} |")
    print("+------------+-----------------+")

    print("\n" + "=" * 30 + "\n")

    # --- Print the Detailed PR List ---
    print("List of PRs and Creation Dates")
    print("---------------------------------")

    if not pr_list:
        print("No pull requests found.")
    else:
        pr_list.sort(key=lambda x: x['number'])
        for item in pr_list:
            print(f"PR: {item['number']}  -  Date: {item['date']}")
    print("---------------------------------")


def main():
    """
    Main function to handle command-line arguments and file reading.
    """
    # Check if the user provided a file path as a command-line argument
    if len(sys.argv) < 2:
        print("Usage: python process_prs.py <path_to_your_json_file>")
        sys.exit(1)  # Exit with an error code

    file_path = sys.argv[1]

    # Check if the provided file path actually exists
    if not os.path.exists(file_path):
        print(f"Error: The file '{file_path}' was not found.")
        sys.exit(1)

    # Read the JSON data from the specified file
    try:
        # Use 'utf-8' encoding for broad compatibility
        with open(file_path, 'r', encoding='utf-8') as f:
            json_from_file = f.read()
    except Exception as e:
        print(f"Error reading the file: {e}")
        sys.exit(1)

    # Call the processing function with the data from the file
    process_github_data(json_from_file)


# This ensures the main() function is called only when the script is executed directly
if __name__ == "__main__":
    main()