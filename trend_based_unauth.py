from datetime import datetime, timezone
import requests
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor
# --- Configuration ---
# Use the public API endpoint for unauthenticated requests
BSKY_HOST = "https://public.api.bsky.app"
WHATS_HOT_FEED_URI = "at://did:plc:z72i7hdynmk6r22z27h6tvur/app.bsky.feed.generator/whats-hot"
# Maximum number of comments to fetch for each post
MAX_COMMENTS_PER_POST = 150 
# Number of parallel workers for fetching comments
MAX_WORKERS = 10 

def clean_input(input_string):
    """A robust function to remove all non-printable characters from a string."""
    return ''.join(filter(str.isprintable, input_string))

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

def get_whats_hot_classic(max_posts):
    """Fetches posts from the 'What's Hot Classic' feed using pagination."""
    print(f"\nFetching up to {max_posts} posts from 'What's Hot Classic'...")
    all_posts = []
    cursor = None
    
    while len(all_posts) < max_posts:
        limit = min(100, max_posts - len(all_posts))
        if limit <= 0:
            break
        
        params = {"feed": WHATS_HOT_FEED_URI, "limit": limit}
        if cursor:
            params["cursor"] = cursor

        try:
            response = make_public_request("app.bsky.feed.getFeed", params=params)
            if not response:
                print("API request failed or returned no data. Halting.")
                break
            
            posts_on_page = response.get('feed', [])
            if not posts_on_page:
                print("No more posts found in the feed.")
                break
            
            for post in posts_on_page:
                post['comments'] = []

            all_posts.extend(posts_on_page)
            print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")

            cursor = response.get('cursor')
            
            # print(cursor)
            
            if not cursor:
                print("Reached the end of the feed.")
                break
            
            time.sleep(0.5) # Polite delay

        except Exception as e:
            print(f"An error occurred during fetching: {e}")
            break
    
    return all_posts

def fetch_comments_and_replies(post_item):
    """Wrapper function for threading. Fetches comments and replies for a single post."""
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri:
        return post_item

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
    print("--- Bluesky Trending Feed Archiver (Unauthenticated) ---")
    
    num_posts_input = clean_input(input("How many trending posts do you want to fetch? (e.g., 500): "))
    num_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

    start_time, end_time = None, None
    filter_choice = clean_input(input("\nDo you want to filter posts by timestamp? (y/n): ")).lower()
    if filter_choice == 'y':
        try:
            start_input = clean_input(input("Enter start timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            end_input = clean_input(input("Enter end timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            if start_input:
                start_time = datetime.strptime(start_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            if end_input:
                end_time = datetime.strptime(end_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            print("⚠️ Invalid date format. Please use YYYY-MM-DD HH:MM:SS. Aborting.")
            exit(1)
    
    print("\n--- Starting Benchmark ---")
    total_start_time = time.time()

    # --- 1. Fetching Posts ---
    hot_posts = get_whats_hot_classic(max_posts=num_posts)
    print(f"--- 📊 Fetched {len(hot_posts)} initial posts in {time.time() - total_start_time:.2f} seconds ---")

    # --- 2. Filtering Posts by Timestamp ---
    final_posts = []
    if filter_choice == 'y':
        print("\nFiltering posts by timestamp...")
        for post in hot_posts:
            created_at_str = post.get('post', {}).get('record', {}).get('createdAt')
            if created_at_str:
                post_time = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                if (start_time is None or post_time >= start_time) and \
                   (end_time is None or post_time <= end_time):
                    final_posts.append(post)
        print(f"--- Filtered down to {len(final_posts)} posts in the selected time range. ---")
    else:
        final_posts = hot_posts
        
    # --- Add clickable URL to each post ---
    if final_posts:
        print("\nGenerating clickable URLs for posts...")
        for item in final_posts:
            author_handle = item.get('post', {}).get('author', {}).get('handle')
            post_uri = item.get('post', {}).get('uri')
            if author_handle and post_uri:
                post_id = post_uri.split('/')[-1]
                item['post']['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

    # --- 3. Fetching Comments in Parallel ---
    if final_posts:
        print(f"\nFetching comments for {len(final_posts)} posts using {MAX_WORKERS} parallel workers...")
        comment_fetch_start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            final_posts = list(executor.map(fetch_comments_and_replies, final_posts))
        print(f"--- 📊 Fetched comments in {time.time() - comment_fetch_start:.2f} seconds ---")

    print(f"\n✨ --- Total Execution Time: {time.time() - total_start_time:.2f} seconds --- ✨")

    # --- 4. Saving Results ---
    if final_posts:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        output_dir = "trending_model"
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"trending_whats-hot_{timestamp}.json")
        
        print(f"\nSaving {len(final_posts)} posts with comments to '{filename}'...")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(final_posts, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Successfully saved results.")
        except Exception as e:
            print(f"\n❌ Failed to save posts to file. Error: {e}")