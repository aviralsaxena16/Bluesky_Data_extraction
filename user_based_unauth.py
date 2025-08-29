from datetime import datetime, timezone
import requests
import os
import time
import json
from concurrent.futures import ThreadPoolExecutor

# --- Configuration ---
# Use the public API endpoint for unauthenticated requests
BSKY_HOST = "https://public.api.bsky.app" 
# Maximum number of comments to fetch for each post
MAX_COMMENTS_PER_POST = 150 
# Number of parallel workers for fetching comments
MAX_WORKERS = 10 

def clean_input(input_string):
    """
    A robust function to remove all non-printable characters from a string.
    """
    return ''.join(filter(str.isprintable, input_string))

def make_public_request(xrpc_endpoint, params=None):
    """
    A simple, unauthenticated request handler for the public Bluesky API.
    """
    full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
    try:
        response = requests.get(full_url, params=params, timeout=20)
        response.raise_for_status()
        if response.content:
            return response.json()
        return None
    except requests.exceptions.HTTPError as e:
        error_data = e.response.json()
        print(f"❌ An API error occurred: {error_data.get('message', 'No error message provided.')}")
        raise e
    except requests.exceptions.RequestException as e:
        print(f"❌ A network error occurred: {e}")
        raise e

def get_post_thread(post_uri):
    """
    Fetches a post's full thread using the public API.
    """
    try:
        params = {"uri": post_uri, "depth": 2} # Depth 2 gets comments and replies
        data = make_public_request("app.bsky.feed.getPostThread", params=params)
        return data.get('thread', {})
    except Exception as e:
        print(f"Error fetching thread for {post_uri}: {e}")
        return None

def get_all_user_posts(actor_handle, start_time=None, end_time=None, max_posts=None):
    """
    Fetches posts for a given user using pagination, with optional timestamp filtering and limit.
    This function uses pagination via a 'cursor' to fetch all available posts up to the max_posts limit.
    """
    print(f"\nFetching posts for @{actor_handle}...")
    all_posts = []
    cursor = None
    
    # Set unbounded time limits if not provided
    if start_time is None: start_time = datetime.min.replace(tzinfo=timezone.utc)
    if end_time is None: end_time = datetime.max.replace(tzinfo=timezone.utc)
    
    while True:
        params = {"actor": actor_handle, "limit": 100}
        if cursor:
            params["cursor"] = cursor

        try:
            response = make_public_request("app.bsky.feed.getAuthorFeed", params=params)
            posts_on_page = response.get('feed', [])
            if not posts_on_page:
                print("No more posts found for this user.")
                break

            for post in posts_on_page:
                try:
                    # Parse the post's creation timestamp
                    created_at_str = post.get('post', {}).get('record', {}).get('createdAt')
                    if not created_at_str: continue
                    post_time = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
                except (ValueError, KeyError):
                    continue
                
                # Stop if posts are older than the desired start time
                if post_time < start_time:
                    print("Reached posts older than start time. Stopping.")
                    return all_posts

                # Add post if it's within the desired time range
                if start_time <= post_time <= end_time:
                    post['comments'] = [] 
                    all_posts.append(post)
                    if max_posts and len(all_posts) >= max_posts:
                        print(f"Reached requested limit of {max_posts} posts.")
                        return all_posts

            print(f"   Fetched {len(all_posts)} posts so far...")
            cursor = response.get('cursor')
            if not cursor:
                print("Reached the end of the user's feed.")
                break
            
            time.sleep(0.5) # Polite delay between requests

        except Exception as e:
            print(f"An error occurred while fetching posts: {e}")
            break
    
    return all_posts

def search_and_select_user():
    """
    Prompts for a keyword, searches for users via the public API, and lets them select one.
    """
    query = clean_input(input("Enter a keyword to search for users (e.g., nasa): "))
    if not query:
        print("Search canceled.")
        return None
    
    try:
        print(f"Searching for users matching '{query}'...")
        response = make_public_request("app.bsky.actor.searchActors", params={"q": query, "limit": 25})
        actors = response.get('actors', [])
        
        if not actors:
            print("No users found with that keyword.")
            return None
            
        print("\n--- Found Users ---")
        for i, actor in enumerate(actors):
            display_name = f"({actor.get('displayName')})" if actor.get('displayName') else ""
            print(f"[{i+1}] @{actor.get('handle')} {display_name}")
        print("[0] Cancel Search")
        
        while True:
            try:
                choice = int(clean_input(input("Enter the number of the user you want to select: ")))
                if 0 <= choice <= len(actors):
                    if choice == 0:
                        print("Search canceled.")
                        return None
                    return actors[choice - 1]['handle']
                else:
                    print("Invalid number. Please try again.")
            except ValueError:
                print("Invalid input. Please enter a number.")

    except Exception as e:
        print(f"An error occurred during user search: {e}")
        return None

def fetch_comments_and_replies(post_item):
    """
    Wrapper function for threading. Fetches comments and replies for a single post.
    """
    post_uri = post_item.get('post', {}).get('uri')
    if not post_uri:
        return post_item

    print(f"   Fetching comments for post: {post_uri.split('/')[-1]}")
    thread = get_post_thread(post_uri)
    
    if thread and 'replies' in thread:
        for comment_thread in thread['replies'][:MAX_COMMENTS_PER_POST]:
            structured_comment = {
                "post": comment_thread.get('post', {}),
                "replies": [reply.get('post', {}) for reply in comment_thread.get('replies', [])]
            }
            post_item['comments'].append(structured_comment)
    return post_item

if __name__ == "__main__":
    print("--- Bluesky User Post Archiver (Unauthenticated) ---")
    
    target_handle = None
    while True:
        print("\nHow would you like to select a user to archive?")
        print("[1] Enter a user's handle directly")
        print("[2] Search for a user by keyword")
        choice = clean_input(input("Enter your choice (1 or 2): "))
        
        if choice == '1':
            target_handle = clean_input(input("Please enter the user handle (e.g., nasa.bsky.social): "))
            if target_handle: break
        elif choice == '2':
            target_handle = search_and_select_user()
            if target_handle: break
        else:
            print("Invalid choice. Please enter 1 or 2.")

    if not target_handle:
        print("\nNo user selected. Exiting.")
        exit()

    start_time, end_time = None, None
    if clean_input(input("\nDo you want to filter posts by timestamp? (y/n): ")).lower() == 'y':
        try:
            start_input = clean_input(input("Enter start timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            if start_input:
                start_time = datetime.strptime(start_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
            end_input = clean_input(input("Enter end timestamp (YYYY-MM-DD HH:MM:SS, blank for no limit): "))
            if end_input:
                end_time = datetime.strptime(end_input, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            print("⚠️ Invalid date format. Please use YYYY-MM-DD HH:MM:SS. Aborting.")
            exit(1)

    max_posts_input = clean_input(input("Enter max number of posts to fetch (blank for all available): "))
    max_posts = int(max_posts_input) if max_posts_input.isdigit() else None

    print("\n--- Starting Benchmark ---")
    total_start_time = time.time()

    # --- 1. Fetching Posts ---
    post_fetch_start = time.time()
    user_posts = get_all_user_posts(target_handle, start_time, end_time, max_posts)
    post_fetch_end = time.time()
    print(f"--- 📊 Fetched {len(user_posts)} posts in {post_fetch_end - post_fetch_start:.2f} seconds ---")

    # --- 2. Add clickable URL to each post ---
    print("\nGenerating clickable URLs for posts...")
    for item in user_posts:
        author_handle = item.get('post', {}).get('author', {}).get('handle')
        post_uri = item.get('post', {}).get('uri')
        if author_handle and post_uri:
            post_id = post_uri.split('/')[-1]
            item['post']['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

    # --- 3. Fetching Comments in Parallel ---
    if user_posts:
        print(f"\nFetching comments for {len(user_posts)} posts using {MAX_WORKERS} parallel workers...")
        comment_fetch_start = time.time()
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            user_posts = list(executor.map(fetch_comments_and_replies, user_posts))
        comment_fetch_end = time.time()
        print(f"--- 📊 Fetched comments in {comment_fetch_end - comment_fetch_start:.2f} seconds ---")

    total_end_time = time.time()
    print(f"\n✨ --- Total Execution Time: {total_end_time - total_start_time:.2f} seconds --- ✨")
    
    # --- 4. Saving Results ---
    if user_posts:
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        safe_handle = target_handle.replace('.', '_')
        output_dir = "user_model_unauth"
        os.makedirs(output_dir, exist_ok=True)
        filename = os.path.join(output_dir, f"posts_{safe_handle}_{timestamp}.json")
        
        print(f"\nSaving {len(user_posts)} posts with comments to '{filename}'...")
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(user_posts, f, ensure_ascii=False, indent=2)
            print(f"\n✅ Successfully saved results.")
        except Exception as e:
            print(f"\n❌ Failed to save posts to file. Error: {e}")