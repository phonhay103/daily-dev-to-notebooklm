import asyncio
import re
from browser_use import Agent, Browser, BrowserConfig
from firecrawl import FirecrawlApp
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()


class ExtractSchema(BaseModel):
    youtube: str = None


async def main():
    # Part 1: Extract 'r' links from daily.dev
    app = FirecrawlApp()
    user_url = input("Please enter daily.dev search URL: ")
    response = app.scrape_url(
        url=user_url,
        formats=["links", "markdown"],
    )

    # Dictionary to track content type (read post or watch video) for each 'r' link
    r_link_types = {}

    # First pass: Find all posts and their corresponding 'r' links
    post_links = [
        link for link in response.links if "https://app.daily.dev/posts/" in link
    ]
    r_links = [link for link in response.links if "https://api.daily.dev/r/" in link]

    # Dictionary to store complete post URLs for each post ID
    post_id_to_url_map = {}

    # Extract post IDs (assuming format: https://app.daily.dev/posts/{title}-{id})
    for post_link in post_links:
        # Extract the ID from the post URL
        try:
            post_id = post_link.split("-")[-1]
            # Store the complete post URL for each post ID
            post_id_to_url_map[post_id] = post_link
        except Exception:
            continue

    # Match 'r' links to posts while maintaining the original order and preserving duplicates
    # This mapping will be a list of tuples instead of a dictionary to allow duplicates
    post_to_r_mappings = []  # List of (post_id, r_link) tuples to preserve duplicates

    for r_link in r_links:
        try:
            r_id = r_link.split("/")[-1]
            # Check if this ID exists in any post (case-insensitive)
            for post_id in post_id_to_url_map:
                if r_id.lower() == post_id.lower():
                    post_to_r_mappings.append((post_id, r_link))
        except Exception:
            continue

    # Any posts without matching r_links should still be included
    for post_id in post_id_to_url_map:
        if not any(pid == post_id for pid, _ in post_to_r_mappings):
            post_to_r_mappings.append((post_id, None))

    # Parse markdown to find content type for each 'r' link
    if response.markdown:
        markdown_content = response.markdown
        # Look for [Read post](https://api.daily.dev/r/...) or [Watch video](https://api.daily.dev/r/...)
        read_post_links = re.findall(
            r"\[Read post\]\((https://api\.daily\.dev/r/[A-Za-z0-9]+)\)",
            markdown_content,
        )
        watch_video_links = re.findall(
            r"\[Watch video\]\((https://api\.daily\.dev/r/[A-Za-z0-9]+)\)",
            markdown_content,
        )

        # Add types to dictionary
        for link in read_post_links:
            r_link_types[link] = "article"
        for link in watch_video_links:
            r_link_types[link] = "Youtube"

    # Instead of filtering out duplicates, we'll collect all links with their types
    all_links_with_types = []
    youtube_mappings = {}  # Store mappings from r_links to YouTube links

    # Create a mapping from r_links to post URLs, preserving duplicates if any
    r_link_to_post_urls = {}
    for post_id, r_link in post_to_r_mappings:
        if r_link and post_id in post_id_to_url_map:
            if r_link not in r_link_to_post_urls:
                r_link_to_post_urls[r_link] = []
            r_link_to_post_urls[r_link].append(post_id_to_url_map[post_id])

    # Process video links to find YouTube URLs
    for r_link in [
        link for link in r_link_types.keys() if r_link_types.get(link) == "Youtube"
    ]:
        # Make an additional scrape request to get the YouTube link
        try:
            if r_link in r_link_to_post_urls and r_link_to_post_urls[r_link]:
                post_url = r_link_to_post_urls[r_link][
                    0
                ]  # Use the first associated post URL
                print(f"Fetching YouTube link from post URL: {post_url}")
                video_response = app.extract(
                    [post_url],
                    {
                        "prompt": "Extract youtube url",
                        "schema": ExtractSchema.model_json_schema(),
                    },
                )

                # Get the YouTube link directly from the extraction result
                youtube_links = []
                if (
                    video_response
                    and len(video_response) > 0
                    and video_response[0].get("youtube")
                ):
                    youtube_links = [video_response[0]["youtube"]]

                if youtube_links:
                    # Use the first YouTube link found
                    youtube_mappings[r_link] = youtube_links[0]
                    print(f"Found YouTube link for {r_link}: {youtube_links[0]}")
                else:
                    print(f"No YouTube links found for {r_link}")
        except Exception as e:
            print(f"Error fetching YouTube link for {r_link}: {e}")

    # Process all links, including duplicates
    for post_id, r_link in post_to_r_mappings:
        if r_link:  # Some posts might not have corresponding 'r' links
            content_type = r_link_types.get(
                r_link, "article"
            )  # Default to article if type not found

            # Replace with YouTube link if available
            if content_type == "Youtube" and r_link in youtube_mappings:
                all_links_with_types.append((youtube_mappings[r_link], "Youtube"))
            else:
                all_links_with_types.append((r_link, content_type))

    print(f"All links found: {len(response.links)}")
    print(f"Post links found: {len(post_links)}")
    print(f"R links found: {len(r_links)}")
    print(f"Total links for import (including duplicates): {len(all_links_with_types)}")
    for link, content_type in all_links_with_types:
        print(f"{link} - {content_type}")

    # Part 2: Use browser agent to create notebook and import links
    # Configure browser to use Microsoft Edge on Mac
    browser = Browser(
        config=BrowserConfig(
            # Path to Microsoft Edge on macOS
            chrome_instance_path="/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        )
    )

    # Create a sample notebook template with the URLs
    articles = [
        link for link, content_type in all_links_with_types if content_type == "article"
    ]
    videos = [
        link for link, content_type in all_links_with_types if content_type == "Youtube"
    ]

    notebook_content = f"""
<VSCode.Cell language="markdown">
# Daily.dev Content Collection
This notebook contains content imported from daily.dev, including articles and YouTube videos.
</VSCode.Cell>

<VSCode.Cell language="markdown">
## Articles
The following articles have been imported from daily.dev:

{chr(10).join([f"- [{i+1}] {url}" for i, url in enumerate(articles)])}
</VSCode.Cell>

<VSCode.Cell language="markdown">
## Videos
The following YouTube videos have been imported from daily.dev:

{chr(10).join([f"- [{i+1}] {url}" for i, url in enumerate(videos)])}
</VSCode.Cell>
"""

    # Save the notebook content to a file for reference
    with open("notebook_template.xml", "w") as f:
        f.write(notebook_content)

    print("\nGenerated notebook template saved to notebook_template.xml")

    # Create a task description for the initialization agent
    init_task_description = """
    1. Open https://notebooklm.google.com/
    2. Create a new notebook
    3. Notify when the notebook is ready for importing content
    """

    # We'll use a simple function to update progress instead of a separate agent
    def update_progress(articles_done, videos_done, total_articles, total_videos):
        print("\n--- Import Progress Update ---")
        article_percent = (
            articles_done / total_articles * 100 if total_articles > 0 else 0
        )
        video_percent = videos_done / total_videos * 100 if total_videos > 0 else 0
        print(f"Articles: {articles_done}/{total_articles} ({article_percent:.1f}%)")
        print(f"Videos: {videos_done}/{total_videos} ({video_percent:.1f}%)")
        total_done = articles_done + videos_done
        total_items = total_articles + total_videos
        total_percent = total_done / total_items * 100 if total_items > 0 else 0
        print(f"Total: {total_done}/{total_items} ({total_percent:.1f}%)")
        print("-------------------------")

    # Initialize tracking variables
    articles_imported = 0
    videos_imported = 0

    # Create a single browser context for all agents
    print("\nCreating browser context for all agents...")
    async with await browser.new_context() as context:
        # Step 1: Run the initialization agent to create a new notebook
        print("\nStarting initialization agent to create NotebookLM notebook...")
        init_agent = Agent(
            task=init_task_description,
            llm=ChatGoogleGenerativeAI(
                model="gemini-2.5-flash-preview-04-17",
                temperature=0,
            ),
            browser_context=context,
            generate_gif=True,
            max_failures=5,
        )
        await init_agent.run(max_steps=20)

        # Step 2: Import articles with a specialized agent
        print(f"\nStarting article import for {len(articles)} articles...")
        for i, article in enumerate(articles):
            article_task = f"""
            Import the following website into NotebookLM:
            URL: {article}
            """

            print(f"\nImporting article {i+1}/{len(articles)}: {article}")
            article_agent = Agent(
                task=article_task,
                llm=ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash-preview-04-17",
                    temperature=0,
                ),
                browser_context=context,
                generate_gif=False,
                max_failures=3,
            )

            try:
                await article_agent.run(max_steps=20)
                articles_imported += 1
                print(f"✓ Article {i+1} imported successfully")
                update_progress(
                    articles_imported, videos_imported, len(articles), len(videos)
                )
            except Exception as e:
                print(f"✗ Failed to import article {i+1}: {e}")

        # Step 3: Import videos with a specialized agent
        print(f"\nStarting video import for {len(videos)} videos...")
        for i, video in enumerate(videos):
            video_task = f"""
            Import the following Youtube into NotebookLM:
            URL: {video}
            """

            print(f"\nImporting video {i+1}/{len(videos)}: {video}")
            video_agent = Agent(
                task=video_task,
                llm=ChatGoogleGenerativeAI(
                    model="gemini-2.5-flash-preview-04-17",
                    temperature=0,
                ),
                browser_context=context,
                generate_gif=False,
                max_failures=3,
            )

            try:
                await video_agent.run(max_steps=20)
                videos_imported += 1
                print(f"✓ Video {i+1} imported successfully")
                update_progress(
                    articles_imported, videos_imported, len(articles), len(videos)
                )
            except Exception as e:
                print(f"✗ Failed to import video {i+1}: {e}")

        # Final report
        print("\n===== Import Summary =====")
        print(f"Articles: {articles_imported}/{len(articles)} imported")
        print(f"Videos: {videos_imported}/{len(videos)} imported")
        print(
            f"Total: {articles_imported + videos_imported}/{len(articles) + len(videos)} imported"
        )

    # Wait for user input before closing the browser
    input("Press Enter to close the browser...")
    await browser.close()


asyncio.run(main())
