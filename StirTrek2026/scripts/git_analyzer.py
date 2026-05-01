#!/usr/bin/env python3

import subprocess
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone
from itertools import combinations

OUTPUT_FILE = "GIT_ANALYSIS.md"
TOP_N = 50
TWO_YEARS_AGO = datetime.now(timezone.utc) - timedelta(days=365 * 2)


def run_git_command(cmd):
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"Git command failed: {' '.join(cmd)}\n{result.stderr}")
    return result.stdout


def parse_git_log():
    """
    Parse git log once and extract:
    - commit date
    - author
    - files changed
    - insertions/deletions
    """
    cmd = [
        "git", "log",
        "--pretty=format:---COMMIT---%n%H|%an|%ad",
        "--date=iso",
        "--numstat"
    ]

    output = run_git_command(cmd)

    commits = []
    current = None

    for line in output.splitlines():
        if line.startswith("---COMMIT---"):
            if current:
                commits.append(current)
            current = {"files": [], "author": None, "date": None}
        elif "|" in line and current and current["author"] is None:
            _, author, date_str = line.split("|", 2)

            # ✅ Robust timezone-aware parsing
            date_str = date_str.strip()
            current["date"] = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S %z")

            current["author"] = author.strip()

        elif line.strip():
            parts = line.split("\t")
            if len(parts) == 3:
                added, deleted, file = parts
                try:
                    added = int(added)
                    deleted = int(deleted)
                except ValueError:
                    added = deleted = 0
                current["files"].append((file, added, deleted))

    if current:
        commits.append(current)

    return commits


def main():
    commits = parse_git_log()

    # Aggregations
    file_last_modified = {}
    file_change_count = Counter()
    file_authors = defaultdict(set)
    file_churn = Counter()
    cochange_counter = Counter()

    for commit in commits:
        files = [f for f, _, _ in commit["files"]]

        # Co-change pairs
        for a, b in combinations(sorted(set(files)), 2):
            cochange_counter[(a, b)] += 1

        for file, added, deleted in commit["files"]:
            file_change_count[file] += 1
            file_authors[file].add(commit["author"])
            file_churn[file] += (added + deleted)

            # Track most recent modification
            if file not in file_last_modified or commit["date"] > file_last_modified[file]:
                file_last_modified[file] = commit["date"]

    # ---- Calculations ----

    # Recently changed
    recent_files = sorted(file_last_modified.items(), key=lambda x: x[1], reverse=True)[:TOP_N]

    # Most changed
    most_changed = file_change_count.most_common(TOP_N)

    # Most contributors
    most_contributors = sorted(
        [(f, len(authors)) for f, authors in file_authors.items()],
        key=lambda x: x[1],
        reverse=True
    )[:TOP_N]

    # Single-owner files
    single_owner_files = [(f, list(authors)[0]) for f, authors in file_authors.items() if len(authors) == 1]
    single_owner_count = len(single_owner_files)

    single_owner_user_counts = Counter(user for _, user in single_owner_files)

    # Co-change
    top_cochanges = cochange_counter.most_common(TOP_N)

    # Churn
    top_churn = file_churn.most_common(TOP_N)

    # Stale files (not changed in 2 years)
    stale_files = [
        (f, date) for f, date in file_last_modified.items()
        if date < TWO_YEARS_AGO
    ]
    stale_files = sorted(stale_files, key=lambda x: x[1])[:TOP_N]

    # ---- Write Markdown ----

    with open(OUTPUT_FILE, "w") as f:
        f.write("# Git Analysis Report\n\n")

        # Recent
        f.write("## Top 50 Recently Changed Files\n\n")
        f.write("| File | Last Modified |\n|------|---------------|\n")
        for file, date in recent_files:
            f.write(f"| {file} | {date} |\n")

        # Most changed
        f.write("\n## Top 50 Most Frequently Changed Files\n\n")
        f.write("| File | Change Count |\n|------|--------------|\n")
        for file, count in most_changed:
            f.write(f"| {file} | {count} |\n")

        # Most contributors
        f.write("\n## Top 50 Files with Most Contributors\n\n")
        f.write("| File | Contributor Count |\n|------|-------------------|\n")
        for file, count in most_contributors:
            f.write(f"| {file} | {count} |\n")

        # Single owner
        f.write("\n## Files with a Single Contributor\n\n")
        f.write(f"Total Files: {single_owner_count}\n\n")
        f.write("| File | Owner |\n|------|-------|\n")
        for file, owner in single_owner_files[:TOP_N]:
            f.write(f"| {file} | {owner} |\n")

        f.write("\n### Single Owner User Totals\n\n")
        f.write("| User | File Count |\n|------|-----------|\n")
        for user, count in single_owner_user_counts.most_common():
            f.write(f"| {user} | {count} |\n")

        # Co-change
        f.write("\n## Top 50 Co-Changed File Pairs\n\n")
        f.write("| File A | File B | Count |\n|--------|--------|-------|\n")
        for (a, b), count in top_cochanges:
            f.write(f"| {a} | {b} | {count} |\n")

        # Churn
        f.write("\n## Top 50 Files by Churn (Added + Deleted Lines)\n\n")
        f.write("| File | Churn |\n|------|-------|\n")
        for file, churn in top_churn:
            f.write(f"| {file} | {churn} |\n")

        # Stale
        f.write("\n## Top 50 Stale Files (Not Modified in 2+ Years)\n\n")
        f.write("| File | Last Modified |\n|------|---------------|\n")
        for file, date in stale_files:
            f.write(f"| {file} | {date} |\n")

    print(f"Analysis written to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()

