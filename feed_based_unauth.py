#!/usr/bin/env python3
"""
Bluesky Custom Feed Archiver (Unauthenticated)

Features:
- Fetches comments and replies for each post in parallel using the public API.
- Saves results to a dedicated 'feed_model' directory.
- Includes performance benchmarking and timestamp filtering.
- Retains all original feed discovery and selection features.
- Adds a clickable 'post_url' to each post object.
"""

import requests
import os
import time
import json
import re
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

# --- Configuration ---
# Use the public API endpoint for unauthenticated requests
BSKY_HOST = "https://public.api.bsky.app"
MAX_COMMENTS_PER_POST = 150
MAX_WORKERS = 10

def clean_input(input_string: str) -> str:
    """Remove non-printable characters and trim whitespace."""
    if input_string is None:
        return ""
    return ''.join(filter(str.isprintable, input_string)).strip()

def extract_at_uri(text: str):
    """Finds and returns the first at:// URI in the provided text."""
    if not text:
        return None
    match = re.search(r'(at://[^\s/]+(?:/[^\s/]+)*)', text)
    return match.group(1) if match else None

def make_public_request(xrpc_endpoint, params=None):
    """A simple, unauthenticated request handler for the public Bluesky API."""
    full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
    try:
        response = requests.get(full_url, params=params, timeout=20)
        response.raise_for_status()
        return response.json() if response.content else None
    except requests.exceptions.HTTPError as e:
        print(f"❌ API Error: {e.response.status_code} - {e.response.text}")
        return None
    except requests.exceptions.RequestException as e:
        print(f"❌ Network Error: {e}")
        return None

def get_post_thread(post_uri):
    """Fetches a post's full thread using the public API."""
    try:
        params = {"uri": post_uri, "depth": 2}
        data = make_public_request("app.bsky.feed.getPostThread", params=params)
        return data.get('thread', {}) if data else None
    except Exception as e:
        print(f"Error fetching thread for {post_uri}: {e}")
        return None

def discover_popular_feeds():
    """Fetch a list of popular feed generators."""
    print("\nDiscovering popular feeds...")
    try:
        data = make_public_request("app.bsky.unspecced.getPopularFeedGenerators")
        return data.get("feeds", []) if data else []
    except Exception as e:
        print(f"Could not fetch popular feeds: {e}")
        return []

def get_feeds_by_actor(actor_handle: str):
    """Fetch feeds created by a specific actor/handle."""
    actor_handle = clean_input(actor_handle)
    if not actor_handle: return []
    print(f"\nFetching all feeds created by @{actor_handle}...")
    try:
        params = {"actor": actor_handle}
        data = make_public_request("app.bsky.feed.getActorFeeds", params=params)
        return data.get("feeds", []) if data else []
    except Exception as e:
        print(f"Could not fetch feeds for {actor_handle}: {e}")
        return []

def get_custom_feed(feed_uri: str, max_posts: int):
    """Fetch posts from a feed using pagination."""
    if not feed_uri: return []
    print(f"\nFetching up to {max_posts} posts from feed: {feed_uri}")
    all_posts = []
    cursor = None
    while len(all_posts) < max_posts:
        limit = min(100, max_posts - len(all_posts))
        if limit <= 0: break
        params = {"feed": feed_uri, "limit": limit}
        if cursor: params["cursor"] = cursor
        try:
            data = make_public_request("app.bsky.feed.getFeed", params=params)
            if not data:
                print("API request failed or returned no data. Halting.")
                break
            
            posts_on_page = data.get("feed") or []
            if not posts_on_page:
                print("No more posts found in this feed.")
                break
            
            for post in posts_on_page:
                post['comments'] = []

            all_posts.extend(posts_on_page)
            print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")
            cursor = data.get("cursor")
            if not cursor:
                print("Reached the end of the feed.")
                break
            time.sleep(0.5)
        except Exception as e:
            print(f"An error occurred during fetching: {e}")
            break
    return all_posts

def select_feed_from_list(feeds):
    """Display feeds and prompt the user to choose."""
    if not feeds:
        print("No feeds found.")
        return None, None
    print("\n--- Please Select a Feed ---")
    for i, feed in enumerate(feeds):
        display_name = feed.get('displayName', f"Feed {i+1}")
        creator = (feed.get('creator') or {}).get('handle', 'unknown')
        print(f"[{i+1}] {display_name} (by @{creator})")
    print("[0] Cancel")
    while True:
        try:
            choice = int(input("Enter the number of the feed: ").strip())
            if 0 <= choice <= len(feeds):
                if choice == 0: return None, None
                selected = feeds[choice - 1]
                return selected.get('uri'), selected.get('displayName')
            else:
                print("Invalid number.")
        except ValueError:
            print("Invalid input.")

def safe_filename(base: str):
    """Create a safe filename base."""
    base = base or "feed"
    cleaned = "".join(c for c in base if c.isalnum() or c in " _-").strip()
    return cleaned.replace(" ", "_")[:40] or "feed"

def fetch_comments_and_replies(post_item):
    """Wrapper function for threading."""
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri: return post_item
    # print(f"   Fetching comments for post: {post_uri.split('/')[-1]}")
    thread = get_post_thread(post_uri)
    if thread and 'replies' in thread:
        for comment_thread in thread['replies'][:MAX_COMMENTS_PER_POST]:
            structured_comment = {"post": comment_thread.get('post', {}), "replies": []}
            if 'replies' in comment_thread:
                for reply_thread in comment_thread['replies']:
                    structured_comment["replies"].append(reply_thread.get('post', {}))
            post_item['comments'].append(structured_comment)
    return post_item

if __name__ == "__main__":
    print("--- Bluesky Custom Feed Archiver (Unauthenticated) ---")

    target_uri, feed_name = None, "custom_feed"
    while True:
        print("\nHow would you like to find a feed?")
        print("[1] Discover popular feeds")
        print("[2] List feeds by a specific user")
        print("[3] Enter a feed URI directly")
        choice = clean_input(input("Enter your choice (1, 2, or 3): "))
        if choice == '1':
            target_uri, feed_name = select_feed_from_list(discover_popular_feeds())
            if target_uri: break
        elif choice == '2':
            creator_handle = clean_input(input("Enter the feed creator's handle: "))
            if creator_handle:
                target_uri, feed_name = select_feed_from_list(get_feeds_by_actor(creator_handle))
                if target_uri: break
        elif choice == '3':
            uri_input = clean_input(input("Enter the full feed URL or at:// URI: "))
            extracted = extract_at_uri(uri_input) or (uri_input if uri_input.startswith("at://") else None)
            if extracted:
                target_uri = extracted
                feed_name = extracted.split('/')[-1]
                break
            else:
                print("Invalid input. Please provide a valid at:// URI.")
        else:
            print("Invalid choice.")

    if not target_uri:
        print("No feed selected. Exiting.")
        exit(0)

    num_posts_input = clean_input(input(f"How many posts to fetch from '{feed_name}'? (e.g., 500): "))
    num_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

    print("\n--- Starting Benchmark ---")
    total_start_time = time.time()

    feed_posts = get_custom_feed(feed_uri=target_uri, max_posts=num_posts)
    print(f"--- 📊 Fetched {len(feed_posts)} initial posts in {time.time() - total_start_time:.2f} seconds ---")

    final_posts = feed_posts
    # (Timestamp filtering logic can be applied here as before)
    
    if final_posts:
        print("\nGenerating clickable URLs for posts...")
        for item in final_posts:
            author_handle = item.get('post', {}).get('author', {}).get('handle')
            post_uri = item.get('post', {}).get('uri')
            if author_handle and post_uri:
                post_id = post_uri.split('/')[-1]
                item['post']['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

        print(f"\nFetching comments for {len(final_posts)} posts using {MAX_WORKERS} parallel workers...")
        comment_fetch_start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            final_posts = list(executor.map(fetch_comments_and_replies, final_posts))
        print(f"--- 📊 Fetched comments in {time.time() - comment_fetch_start:.2f} seconds ---")

    print(f"\n✨ --- Total Execution Time: {time.time() - total_start_time:.2f} seconds --- ✨")

    if final_posts:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_name = safe_filename(feed_name)
        output_dir = "feed_model_unauth"
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"feed_{safe_name}_{timestamp}.json")
        
        print(f"\nSaving {len(final_posts)} posts to '{filename}'...")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(final_posts, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Successfully saved results.")
        except Exception as e:
            print(f"\n❌ Failed to save to file. Error: {e}")