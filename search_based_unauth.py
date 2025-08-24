# import os
# import time
# import json
# import random
# from concurrent.futures import ThreadPoolExecutor
# from datetime import datetime, date
# # Use the curl_cffi library to impersonate a real browser
# from curl_cffi.requests import Session, RequestsError

# # --- Configuration ---
# BSKY_API_HOST = "https://api.bsky.app"
# MAX_COMMENTS_PER_POST = 150
# MAX_WORKERS = 10
# MAX_RETRIES = 2 # Use fewer retries per proxy

# # --- Proxy Configuration ---
# # PASTE YOUR LIST OF PROXIES HERE.
# # The script will rotate through them.
# # Format: "IP:PORT"
# PROXY_LIST = [
#     "108.141.130.146",
#     "101.255.119.206",  # Replace with your first real proxy
#     "108.162.192.0",

#        # Replace with your second real proxy
#     # Add as many proxies as you have
# ]

# if not PROXY_LIST or "123.45.67.89:8080" in PROXY_LIST:
#     print("⚠️ WARNING: You are using placeholder proxies. Please update the PROXY_LIST.")
#     # exit() # You can uncomment this to prevent running without real proxies

# print(f"✅ Loaded {len(PROXY_LIST)} proxies for rotation.")

# # --- Functions ---

# def clean_input(input_string):
#     """A robust function to remove all non-printable characters from a string."""
#     return ''.join(filter(str.isprintable, input_string))

# def get_post_thread_unauthenticated(post_uri):
#     # This function can also be updated to rotate proxies if needed,
#     # but the primary block is during the search pagination.
#     # For now, we'll focus on the search function.
#     # (Implementation is left simple for clarity)
#     try:
#         session = Session(impersonate="chrome120")
#         params = {"uri": post_uri, "depth": 2}
#         url = f"{BSKY_API_HOST}/xrpc/app.bsky.feed.getPostThread"
#         response = session.get(url, params=params, timeout=30)
#         response.raise_for_status()
#         return response.json().get('thread', {})
#     except RequestsError as e:
#         print(f"❌ Failed to fetch thread for {post_uri}: {e}")
#         return None


# def search_posts_unauthenticated(query, sort_order='latest', max_posts=1000):
#     """Performs a public search using PROXY ROTATION for each paginated request."""
#     print(f"\nSearching for posts with query: '{query}' (sorted by {sort_order})")
#     print(f"Fetching up to {max_posts} posts...")
#     all_posts = []
#     cursor = None
#     url = f"{BSKY_API_HOST}/xrpc/app.bsky.feed.searchPosts"

#     while len(all_posts) < max_posts:
#         limit = min(100, max_posts - len(all_posts))
#         if limit <= 0: break

#         params = {"q": query, "sort": sort_order, "limit": limit}
#         if cursor: params["cursor"] = cursor
        
#         response_data = None
#         for attempt in range(MAX_RETRIES):
#             try:
#                 # *** CORE LOGIC CHANGE: SELECT A NEW PROXY FOR EACH REQUEST ***
#                 chosen_proxy = random.choice(PROXY_LIST)
#                 proxies = {"http": f"http://{chosen_proxy}", "https": f"http://{chosen_proxy}"}
#                 print(f"   Attempting fetch with proxy: {chosen_proxy}")

#                 # Create a new session for each request to ensure a clean slate
#                 session = Session(
#                     proxies=proxies,
#                     impersonate="chrome120", # This mimics a real browser's TLS signature
#                     timeout=30
#                 )
                
#                 response = session.get(url, params=params)
#                 response.raise_for_status()
#                 response_data = response.json()
#                 break # Success! Exit the retry loop.

#             except RequestsError as e:
#                 print(f"   ⚠️ Proxy {chosen_proxy} failed (Attempt {attempt + 1}/{MAX_RETRIES}): {e}")
#                 if attempt < MAX_RETRIES - 1:
#                     time.sleep(1) # Wait a second before retrying with a new proxy
#                 else:
#                     print(f"   ❌ All retries failed for this page. Moving on or stopping.")
        
#         if not response_data:
#             print("❌ Halting search due to persistent network failures.")
#             break
            
#         posts_on_page = response_data.get('posts', [])
#         if not posts_on_page:
#             print("No more posts found. Halting.")
#             break

#         for post in posts_on_page:
#             post['comments'] = []
#         all_posts.extend(posts_on_page)
#         print(f"   ✅ Fetched {len(posts_on_page)} posts. Total so far: {len(all_posts)}")
        
#         cursor = response_data.get('cursor')
#         if not cursor:
#             print("Reached the end of the search results.")
#             break
        
#         # Add a polite, randomized delay before the next page request
#         delay = random.uniform(2, 5)
#         print(f"   Waiting for {delay:.2f} seconds...")
#         time.sleep(delay)

#     return all_posts

# # The fetch_comments_and_replies and __main__ blocks do not need any changes.
# # They will automatically use the new, more robust search function.

# def fetch_comments_and_replies(post_item):
#     """
#     Wrapper function for threading. Fetches comments and replies for a single post.
#     """
#     post_uri = post_item.get('uri')
#     if not post_uri:
#         return post_item

#     # This part can be slow if fetching comments for many posts.
#     # For now, it doesn't use proxies, but could be adapted if needed.
#     print(f"   Fetching comments for post: {post_uri.split('/')[-1]}")
#     thread = get_post_thread_unauthenticated(post_uri)
    
#     if thread and 'replies' in thread:
#         top_level_comments = thread['replies']
        
#         for comment_thread in top_level_comments[:MAX_COMMENTS_PER_POST]:
#             comment_post = comment_thread.get('post', {})
#             structured_comment = {"post": comment_post, "replies": []}

#             if 'replies' in comment_thread:
#                 for reply_thread in comment_thread['replies']:
#                     structured_comment["replies"].append(reply_thread.get('post', {}))
            
#             post_item['comments'].append(structured_comment)

#     return post_item

# if __name__ == "__main__":
#     # Your __main__ block remains exactly the same.
#     # It will call the new search_posts_unauthenticated function.
#     print("--- Bluesky Public Discovery Tool with Proxy Rotation ---")
    
#     print("\n--- Build Your Search Query ---")
    
#     include_terms = clean_input(input('Enter search terms (use "quotes for exact phrases"): '))
#     exclude_terms_raw = clean_input(input('Enter words to EXCLUDE (optional, separate with spaces): '))
#     exclude_terms = [f"-{term.strip()}" for term in exclude_terms_raw.split() if term.strip()]
    
#     final_query_parts = [include_terms] + exclude_terms
#     final_query = " ".join(final_query_parts).strip()
    
#     if not final_query:
#         print("No search query provided. Exiting.")
#         exit()

#     while True:
#         sort_choice = clean_input(input("Sort by [1] Top or [2] Latest? (Enter 1 or 2): "))
#         if sort_choice == '1':
#             sort_order = 'top'
#             break
#         elif sort_choice == '2':
#             sort_order = 'latest'
#             break
#         else:
#             print("Invalid choice. Please enter 1 or 2.")
    
#     num_posts_input = clean_input(input("How many posts do you want to fetch? (e.g., 500): "))
#     num_posts = int(num_posts_input) if num_posts_input.isdigit() else 500

#     print("\n--- Starting Benchmark ---")
#     total_start_time = time.time()

#     # --- 1. Fetching Posts ---
#     post_fetch_start = time.time()
#     fetched_posts = search_posts_unauthenticated(final_query, sort_order, num_posts)
#     post_fetch_end = time.time()
#     print(f"--- 📊 Fetched {len(fetched_posts)} posts in {post_fetch_end - post_fetch_start:.2f} seconds ---")

#     # --- 2. Filtering ---
#     # ... (rest of your script is unchanged)
#     final_posts = []
#     lang_choice = clean_input(input("\nFilter by language? (Enter 2-letter code like 'en', 'es', or leave blank for all): ")).lower()
#     if not lang_choice:
#         final_posts = fetched_posts
#     else:
#         for post in fetched_posts:
#             langs = post.get('record', {}).get('langs', [])
#             if langs and lang_choice in langs:
#                 final_posts.append(post)
#         print(f"Filtered down to {len(final_posts)} posts in language '{lang_choice}'.")

#     ts_filter_choice = clean_input(input("\nDo you want to filter by date? (y/n): ")).lower()
#     if ts_filter_choice == 'y':
#         try:
#             lower_limit_str = clean_input(input("Enter start date (YYYY-MM-DD, blank for no limit): ")).strip()
#             upper_limit_str = clean_input(input("Enter end date (YYYY-MM-DD, blank for no limit): ")).strip()

#             lower_limit_date = date.fromisoformat(lower_limit_str) if lower_limit_str else date.min
#             upper_limit_date = date.fromisoformat(upper_limit_str) if upper_limit_str else date.max

#             filtered_by_time = []
#             for post in final_posts:
#                 created_at_str = post.get('record', {}).get('createdAt')
#                 if created_at_str:
#                     post_date = datetime.fromisoformat(created_at_str.replace("Z", "+00:00")).date()
#                     if lower_limit_date <= post_date <= upper_limit_date:
#                         filtered_by_time.append(post)
            
#             print(f"Filtered down to {len(filtered_by_time)} posts by date.")
#             final_posts = filtered_by_time
#         except ValueError:
#             print("⚠️ Invalid date format. Please use YYYY-MM-DD.")
    
#     # --- Add clickable URL to each post ---
#     print("\nGenerating clickable URLs for posts...")
#     for item in final_posts:
#         author_handle = item.get('author', {}).get('handle')
#         post_uri = item.get('uri')
#         if author_handle and post_uri:
#             post_id = post_uri.split('/')[-1]
#             item['post_url'] = f"https://bsky.app/profile/{author_handle}/post/{post_id}"

#     # --- 3. Fetching Comments in Parallel ---
#     if final_posts:
#         print(f"\nFetching comments for {len(final_posts)} posts using {MAX_WORKERS} parallel workers...")
#         comment_fetch_start = time.time()
#         with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
#             results = list(executor.map(fetch_comments_and_replies, final_posts))
#         comment_fetch_end = time.time()
#         print(f"--- 📊 Fetched comments in {comment_fetch_end - comment_fetch_start:.2f} seconds ---")
#         final_posts = results

#     total_end_time = time.time()
#     print(f"\n✨ --- Total Execution Time: {total_end_time - total_start_time:.2f} seconds --- ✨")

#     # --- 4. Saving Results ---
#     if final_posts:
#         timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
#         safe_query = "".join(c for c in final_query if c.isalnum() or c in (' ', '_')).rstrip()
#         safe_query = safe_query.replace(' ', '_')[:30]

#         output_dir = "search_model_public"
#         os.makedirs(output_dir, exist_ok=True)
#         filename = os.path.join(output_dir, f"search_{safe_query}_{timestamp}.json")
        
#         print(f"\nSaving {len(final_posts)} posts with comments to '{filename}'...")
#         try:
#             with open(filename, 'w', encoding='utf-8') as f:
#                 json.dump(final_posts, f, ensure_ascii=False, indent=2)
#             print(f"\n✅ Successfully saved results.")
#         except Exception as e:
#             print(f"\n❌ Failed to save posts to file. Error: {e}")