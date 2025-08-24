# import requests
# import os
# import time
# import json
# import random
# from datetime import datetime, timezone, date
# from concurrent.futures import ThreadPoolExecutor

# # --- Configuration ---
# BSKY_HOST = "https://public.api.bsky.app"
# MAX_COMMENTS_PER_POST = 150
# MAX_WORKERS = 10

# # --- Advanced: Browser-like Headers ---
# # This makes our script look like a real browser to avoid being blocked.
# BROWSER_HEADERS = {
#     "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
#     "Accept": "application/json, text/plain, */*",
#     "Accept-Language": "en-US,en;q=0.9",
#     "Accept-Encoding": "gzip, deflate, br",
#     "DNT": "1",
#     "Sec-GPC": "1",
#     "Connection": "keep-alive",
# }

# # Use a session object to make requests
# session = requests.Session()
# session.headers.update(BROWSER_HEADERS)

# def clean_input(input_string):
#     """A robust function to remove all non-printable characters from a string."""
#     return ''.join(filter(str.isprintable, input_string))

# def make_public_request(xrpc_endpoint, params=None):
#     """A highly robust, unauthenticated request handler that mimics a browser."""
#     full_url = f"{BSKY_HOST}/xrpc/{xrpc_endpoint}"
#     try:
#         response = session.get(full_url, params=params, timeout=30)
#         response.raise_for_status()
#         if response.text:
#             return response.json()
#         else:
#             print("⚠️ Warning: API returned a successful but empty response.")
#             return None
#     except requests.exceptions.HTTPError as e:
#         # Provide more detailed error info
#         print(f"❌ HTTP Error: {e.response.status_code} Forbidden. The server is blocking our requests.")
#         print("   This is likely due to anti-bot protection. Try again later or from a different network.")
#         return None
#     except json.JSONDecodeError:
#         print(f"❌ Failed to decode JSON. The server might have sent an error page instead of data.")
#         return None
#     except requests.exceptions.RequestException as e:
#         print(f"❌ A network error occurred: {e}")
#         return None

# def get_post_thread(post_uri):
#     """Fetches a post's full thread using the public API."""
#     params = {"uri": post_uri, "depth": 2}
#     data = make_public_request("app.bsky.feed.getPostThread", params=params)
#     return data.get('thread', {}) if data else None

# def search_posts_advanced(query, sort_order='latest', max_posts=1000):
#     """Performs an advanced search for posts with pagination."""
#     print(f"\nSearching for posts with query: '{query}' (sorted by {sort_order})")
#     print(f"Attempting to fetch up to {max_posts} posts...")
    
#     all_posts = []
#     cursor = None
    
#     while len(all_posts) < max_posts:
#         limit = min(100, max_posts - len(all_posts))
#         if limit <= 0:
#             break

#         params = {"q": query, "sort": sort_order, "limit": limit}
#         if cursor:
#             params["cursor"] = cursor

#         response = make_public_request("app.bsky.feed.searchPosts", params=params)
        
#         if not response:
#             print("Halting search due to an API error.")
#             break
            
#         posts_on_page = response.get('posts', [])
#         if not posts_on_page:
#             print("No more posts found for this search.")
#             break
        
#         for post in posts_on_page:
#             post['comments'] = []
        
#         all_posts.extend(posts_on_page)
#         print(f"   Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")

#         cursor = response.get('cursor')
#         if not cursor:
#             print("Reached the end of the search results.")
#             break
        
#         # --- Add a randomized delay to appear less robotic ---
#         time.sleep(random.uniform(0.5, 1.5))
    
#     return all_posts

# def fetch_comments_and_replies(post_item):
#     """Wrapper function for threading to fetch comments."""
#     post_uri = post_item.get('uri')
#     if not post_uri:
#         return post_item
#     thread = get_post_thread(post_uri)
#     if thread and 'replies' in thread:
#         for comment_thread in thread['replies'][:MAX_COMMENTS_PER_POST]:
#             structured_comment = {
#                 "post": comment_thread.get('post', {}),
#                 "replies": [reply.get('post', {}) for reply in comment_thread.get('replies', [])]
#             }
#             post_item['comments'].append(structured_comment)
#     return post_item

# if __name__ == "__main__":
#     print("--- Bluesky Advanced Discovery Tool (Final Unauthenticated Version) ---")
    
#     print("\n--- Build Your Search Query ---")
#     print("Tip: If you get blocked, try sorting by 'Latest' instead of 'Top' for very common search terms.")
    
#     include_terms = clean_input(input('Enter search terms: '))
#     exclude_terms_raw = clean_input(input('Enter words to EXCLUDE (optional): '))
#     exclude_terms = [f"-{term.strip()}" for term in exclude_terms_raw.split() if term.strip()]
#     final_query = " ".join([include_terms] + exclude_terms).strip()
    
#     if not final_query:
#         print("No search query provided. Exiting.")
#         exit()

#     while True:
#         sort_choice = clean_input(input("Sort by [1] Top or [2] Latest? (Enter 1 or 2): "))
#         if sort_choice in ['1', '2']:
#             sort_order = 'top' if sort_choice == '1' else 'latest'
#             break
#         else:
#             print("Invalid choice.")
    
#     num_posts_input = clean_input(input("How many posts to fetch? (e.g., 500): "))
#     max_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

#     print("\n--- Starting Search ---")
#     start_time = time.time()
    
#     fetched_posts = search_posts_advanced(final_query, sort_order, max_posts)
    
#     print(f"--- 📊 Fetched {len(fetched_posts)} posts in {time.time() - start_time:.2f} seconds ---")

#     final_posts = fetched_posts
#     # (The rest of your script for filtering, adding URLs, fetching comments, and saving remains the same)
#     # --- Add clickable URL to each post ---
#     if final_posts:
#         print("\nGenerating clickable URLs for posts...")
#         for item in final_posts:
#             author_handle = item.get('author', {}).get('handle')
#             post_uri = item.get('uri')
#             if author_handle and post_uri:
#                 post_id = post_uri.split('/')[-1]
#                 item['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

#     # --- Fetching Comments in Parallel ---
#     if final_posts:
#         print(f"\nFetching comments for {len(final_posts)} posts using {MAX_WORKERS} parallel workers...")
#         comment_fetch_start = time.time()
#         with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
#             final_posts = list(executor.map(fetch_comments_and_replies, final_posts))
#         print(f"--- 📊 Fetched comments in {time.time() - comment_fetch_start:.2f} seconds ---")

#     print(f"\n✨ --- Total Execution Time: {time.time() - start_time:.2f} seconds --- ✨")

#     # --- Saving Results ---
#     if final_posts:
#         timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#         safe_query = "".join(c for c in final_query if c.isalnum() or c in (' ', '_')).rstrip().replace(' ', '_')[:30]
#         output_dir = "search_model"
#         os.makedirs(output_dir, exist_ok=True)
#         filename = os.path.join(output_dir, f"search_{safe_query}_{timestamp}.json")
        
#         print(f"\nSaving {len(final_posts)} posts to '{filename}'...")
#         try:
#             with open(filename, 'w', encoding='utf-8') as f:
#                 json.dump(final_posts, f, ensure_ascii=False, indent=2)
#             print(f"\n✅ Successfully saved results.")
#         except Exception as e:
#             print(f"\n❌ Failed to save to file. Error: {e}")