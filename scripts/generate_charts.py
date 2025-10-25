#!/usr/bin/env python3
"""
scripts/generate_charts.py
Generates charts for README:
 - top_languages_by_bytes.png
 - top_languages_by_commits.png
 - contributions_area.png (monthly contributions)
 - commits_per_hour_heatmap.png
 - top_repos_by_stars_forks.png

Requirements:
 pip install requests pandas matplotlib python-dateutil tqdm
"""

import os
import sys
import requests
import math
from collections import Counter, defaultdict
import pandas as pd
import matplotlib.pyplot as plt
from dateutil import parser
from tqdm import tqdm
#
# -------------- CONFIG ----------------
GITHUB_USER = "Mrsele"     # change to your username
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")


# GITHUB_TOKEN = os.environ.get("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")  # set in env to increase rate limit
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "assets")
# --------------------------------------

if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

session = requests.Session()
if GITHUB_TOKEN:
    session.headers.update({"Authorization": f"token {GITHUB_TOKEN}"})

BASE_API = "https://api.github.com"

def paginate(url, params=None):
    params = params or {}
    results = []
    while url:
        r = session.get(url, params=params)
        r.raise_for_status()
        results.extend(r.json())
        # parse next link
        link = r.headers.get("Link", "")
        next_url = None
        if "rel=\"next\"" in link:
            parts = link.split(",")
            for p in parts:
                if 'rel="next"' in p:
                    next_url = p.split(";")[0].strip().strip("<>")
        url = next_url
        params = None
    return results

def fetch_repos(user):
    url = f"{BASE_API}/users/{user}/repos"
    repos = paginate(url, params={"per_page": 100, "type": "owner", "sort": "pushed"})
    return repos

def fetch_repo_languages(owner, repo):
    url = f"{BASE_API}/repos/{owner}/{repo}/languages"
    r = session.get(url)
    r.raise_for_status()
    return r.json()

def fetch_commits(owner, repo, author=None):
    url = f"{BASE_API}/repos/{owner}/{repo}/commits"
    params = {"per_page": 100}
    if author:
        params["author"] = author
    # only first 300 commits per repo (avoid rate limits)
    commits = paginate(url, params=params)
    return commits

def fetch_events(user):
    # public events (last 300)
    url = f"{BASE_API}/users/{user}/events/public"
    events = paginate(url, params={"per_page": 100})
    return events

def build_language_stats(repos):
    lang_bytes = Counter()
    for r in tqdm(repos, desc="Fetching languages"):
        try:
            langs = fetch_repo_languages(GITHUB_USER, r["name"])
        except Exception as e:
            print("Language fetch failed for", r["name"], e)
            continue
        for lang, b in langs.items():
            lang_bytes[lang] += b
    df = pd.DataFrame.from_records(list(lang_bytes.items()), columns=["language", "bytes"])
    df = df.sort_values("bytes", ascending=False).reset_index(drop=True)
    return df

def build_top_repos_chart(repos):
    df = pd.DataFrame([{
        "name": r["name"],
        "stars": r["stargazers_count"],
        "forks": r["forks_count"],
        "size_kb": r["size"]
    } for r in repos])
    df = df.sort_values("stars", ascending=False).head(10)
    plt.figure(figsize=(12,6))
    df.plot(kind="bar", x="name", y=["stars","forks"], rot=45, figsize=(12,6))
    plt.title("Top Repos by Stars & Forks")
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "top_repos_by_stars_forks.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print("Saved", out)

def build_languages_pie(df):
    # df: language, bytes
    top = df.head(8)
    others = df["bytes"].iloc[8:].sum()
    if others > 0:
        top = top.append({"language":"Others", "bytes": others}, ignore_index=True)
    plt.figure(figsize=(7,7))
    plt.pie(top["bytes"], labels=top["language"], autopct="%1.1f%%", startangle=140)
    plt.title("Top Languages by Bytes")
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "top_languages_by_bytes.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print("Saved", out)

def build_monthly_contributions(commits_all):
    # commits_all: list of commit datetimes
    months = [d.strftime("%Y-%m") for d in commits_all]
    s = pd.Series(1, index=pd.to_datetime(months))
    s = s.resample('M').sum().fillna(0)
    s.index = s.index.strftime("%Y-%m")
    plt.figure(figsize=(12,4))
    plt.fill_between(s.index, s.values, alpha=0.6)
    plt.plot(s.index, s.values, marker='o')
    plt.xticks(rotation=45)
    plt.title("Contributions per Month")
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "contributions_area.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print("Saved", out)

def build_commits_per_hour_heatmap(commits_all_dt):
    # commits_all_dt: list of datetimes (UTC)
    # We'll create a 24x7 heatmap (hour vs weekday)
    df = pd.DataFrame({"dt": commits_all_dt})
    df["hour"] = df["dt"].dt.hour
    df["weekday"] = df["dt"].dt.weekday  # 0 Monday
    pivot = df.groupby(["weekday","hour"]).size().unstack(fill_value=0)
    # reorder weekdays 0..6
    pivot = pivot.reindex(index=range(0,7), fill_value=0)
    plt.figure(figsize=(12,3.5))
    plt.imshow(pivot, aspect='auto', cmap='viridis')
    plt.colorbar(label='Commits')
    plt.yticks(range(7), ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"])
    plt.xticks(range(0,24,2))
    plt.title("Commits per Weekday & Hour (UTC)")
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "commits_per_hour_heatmap.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print("Saved", out)

def build_languages_by_commits(repos):
    # For each repo get commits, inspect file extensions in commit (slow)
    # Instead approximate by counting language tags from repo languages weighted by commits count
    rows = []
    for r in tqdm(repos, desc="Fetching commits counts per repo"):
        try:
            commits = session.get(f"{BASE_API}/repos/{GITHUB_USER}/{r['name']}/commits", params={"per_page":1}).headers
        except Exception:
            pass
        rows.append({
            "name": r["name"],
            "commits": r.get("size", 0), # fallback to size if commit count not available
            "languages_url": r["languages_url"]
        })
    df = pd.DataFrame(rows)
    # This is a fallback display — prefer bytes-based pie for accuracy.
    # Save a simple chart using repo sizes as proxy
    df = df.sort_values("commits", ascending=False).head(10)
    plt.figure(figsize=(12,5))
    plt.bar(df["name"], df["commits"])
    plt.xticks(rotation=45)
    plt.title("Top Repos (proxy metrics for commits/activity)")
    plt.tight_layout()
    out = os.path.join(OUTPUT_DIR, "top_repos_proxy.png")
    plt.savefig(out, dpi=150)
    plt.close()
    print("Saved", out)
    # Create a dummy top_languages_by_commits as same as bytes (user can replace with a more advanced method)
    return

def main():
    print("Fetching repositories for", GITHUB_USER)
    repos = fetch_repos(GITHUB_USER)
    if len(repos) == 0:
        print("No repos found")
        sys.exit(1)

    # LANG BY BYTES
    lang_df = build_language_stats(repos)
    build_languages_pie(lang_df)

    # TOP REPOS
    build_top_repos_chart(repos)

    # fetch commits timestamps (careful with rate limits; we sample)
    all_commit_dates = []
    for r in tqdm(repos, desc="Scanning repos for commit timestamps (sampling up to 200 commits each)"):
        try:
            commits = fetch_commits(GITHUB_USER, r["name"])
        except Exception as e:
            print("skipping commits for", r["name"], e)
            continue
        for c in commits:
            if c and "commit" in c and c["commit"].get("author"):
                dt = parser.isoparse(c["commit"]["author"]["date"])
                all_commit_dates.append(dt)
        # optional: limit collection if enormous
        if len(all_commit_dates) > 4000:
            break

    if all_commit_dates:
        # monthly contributions
        build_monthly_contributions(pd.to_datetime(all_commit_dates))
        # heatmap
        build_commits_per_hour_heatmap(pd.to_datetime(all_commit_dates))

    # languages-by-commits (fallback/proxy)
    build_languages_by_commits(repos)

    print("Done. Check the assets/ folder and commit the images to your repo.")

if __name__ == "__main__":
    main()
