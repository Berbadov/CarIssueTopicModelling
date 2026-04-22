from webbrowser import get
from wsgiref import headers
import scrapy
from pathlib import Path
from scrapy.crawler import CrawlerProcess
from scrapy.utils.project import get_project_settings
import json
import os
import re
import requests
import asyncio
import sys

# WE NEED TO DO THREAD-LEVEL EXTRACTION


def load_checkpoint(checkpoint_file):
    """Load the set of already-completed thread URLs from a checkpoint file."""
    if os.path.exists(checkpoint_file):
        with open(checkpoint_file, 'r', encoding='utf-8') as f:
            return set(json.load(f))
    return set()


def save_checkpoint(checkpoint_file, completed_urls):
    """Persist the set of completed thread URLs to a checkpoint file."""
    with open(checkpoint_file, 'w', encoding='utf-8') as f:
        json.dump(list(completed_urls), f, ensure_ascii=False, indent=2)


class MessageSpider(scrapy.Spider):
    name = 'messagespider'

    def __init__(self, urls=None, url=None, max_pages=None, checkpoint_file=None, *args, **kwargs):
        super(MessageSpider, self).__init__(*args, **kwargs)
        # Accept a list of URLs (batch mode) or a single URL
        if urls:
            self.start_urls = list(urls)
        elif url:
            self.start_urls = [url]
        else:
            self.start_urls = ['https://www.golftutkusu.com/topic/18290-golf-7-yag-eksiltme-sorunu/']
        self.max_pages = int(max_pages) if max_pages is not None else 2
        # Per-thread visited URL tracking keyed by base thread URL.
        # This prevents one thread's pagination from interfering with another.
        self.thread_visited: dict = {}
        self.checkpoint_file = checkpoint_file
        self._scraped_thread_urls = set()

    @staticmethod
    def _normalize_url(url):
        """Strip fragment and trailing slash for consistent deduplication."""
        return url.split('#')[0].rstrip('/')

    def _get_thread_visited(self, base_url: str) -> set:
        if base_url not in self.thread_visited:
            self.thread_visited[base_url] = set()
        return self.thread_visited[base_url]

    def get_next_page(self, current_url, base_url):
        """
        Get the next page URL with safety checks, scoped to a single thread.

        Args:
            current_url (str): Current page URL
            base_url (str): Canonical thread URL (no page suffix) used as the
                            per-thread pagination key.

        Returns:
            str: Next page URL or None
        """
        norm = self._normalize_url(current_url)
        visited = self._get_thread_visited(base_url)

        if norm in visited:
            print(f"DEBUG: Current URL already visited: {current_url}")
            return None

        visited.add(norm)

        if len(visited) >= self.max_pages:
            print(f"DEBUG: Reached maximum page limit of {self.max_pages} for thread")
            return None

        next_page = next_page_gatherer(current_url)
        if next_page is None:
            print("DEBUG: No next page URL generated, switching to next link if available.")
            return None

        return next_page


    def get_base_thread_url(self, url):
        """Strip page number from URL to get the canonical thread URL."""
        return re.sub(r'/page/\d+(?:#.*)?$', '', url.rstrip('/'))

    def parse(self, response):
        print(f"DEBUG: Parsing page: {response.url}")  
        
        # Extract thread name from the page
        thread_name = (
            response.xpath('//h1[contains(@class, "ipsType_pageTitle")]//text()').get()
            or response.xpath('//h1[contains(@class, "ipsPageHeader")]//text()').get()
            or response.xpath('//h1//text()').get()
            or response.css('h1::text').get()
            or response.xpath('//title/text()').get()
            or 'Unknown Thread'
        ).strip()

        thread_url = self.get_base_thread_url(response.url)
        self._scraped_thread_urls.add(thread_url)

        messages = []

        # Try multiple XPath patterns to find messages
        message_selectors = [
            '//article/div/div[2]/div/div/div/article/div[1]/div/text()', # Literally extracting from the source
            '//div[contains(@class, "message") or contains(@class, "post")]/text()',
            '//div[contains(@class, "content")]/text()',
            '//article//div[contains(@class, "text")]/text()'
        ]

        for selector in message_selectors:
            found_messages = response.xpath(selector).getall()
            if found_messages:
                messages.extend(found_messages)
                break  # Use first successful selector, but it's problamatic

        print(f"DEBUG: Found {len(messages)} messages on this page")  # Debug message count

        # Clean and yield messages
        for message in messages:
            cleaned_message = message.strip()
            if cleaned_message:
                yield {
                    'message': cleaned_message,
                    'thread_name': thread_name,
                    'thread_url': thread_url,
                }
        
        # Follow pagination if available — scoped to this thread
        next_page = self.get_next_page(response.url, thread_url)
        if next_page is not None:
            print(f"DEBUG: Following pagination to: {next_page}")
            yield response.follow(next_page, callback=self.parse)

    def closed(self, reason):
        """Update the checkpoint file when this spider closes (any reason)."""
        if self.checkpoint_file and self._scraped_thread_urls:
            existing = load_checkpoint(self.checkpoint_file)
            existing.update(self._scraped_thread_urls)
            save_checkpoint(self.checkpoint_file, existing)
            print(f"Checkpoint updated: {len(existing)} thread(s) completed in total.")


def next_page_gatherer(cur_url):
    """
    Generate the next page URL for pagination
    
    Args:
        cur_url (str): Current page URL
        
    Returns:
        str: Next page URL or None if no more pages
    """
    print(f"DEBUG: next_page_gatherer input: {cur_url}")  # Debug input URL
    
    # Handle URL normalization
    cur_url = cur_url.strip()
    if not cur_url:
        print("DEBUG: Empty URL provided")
        return None
    
    # Remove any trailing slashes for consistent processing
    cur_url = cur_url.rstrip('/')
    print(f"DEBUG: Normalized URL: {cur_url}")  # Debug normalized URL
    
    # Check for page pattern - more flexible regex to handle various formats
    match = re.search(r'/page/(\d+)(?:/|#|$)', cur_url)
    print(f"DEBUG: Regex match result: {match}")  # Debug regex matching
    
    if match:
        # We're on a paginated page, increment the page number
        cur_page = int(match.group(1))
        new_page = cur_page + 1
        print(f"DEBUG: Found page {cur_page}, generating page {new_page}")
        new_url = re.sub(r'/page/\d+', f'/page/{new_page}', cur_url)
    else:
        # We're on the first page, generate page 2
        print(f"DEBUG: First page detected, generating page 2")
        new_url = cur_url + '/page/2'

    print(f"DEBUG: Generated next page URL: {new_url}")

    # Check whether the next page actually exists.  The forum redirects to
    # the last valid page (3xx) when the requested page is out of range, so
    # any redirect means we've passed the end of the thread.
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3'
        }
        raw_response = requests.get(new_url, timeout=5, allow_redirects=False, headers=headers)
        print(f"DEBUG: Next page HTTP {raw_response.status_code}: {new_url}")
        if 300 <= raw_response.status_code < 400:  # any redirect = page out of range
            print(f"DEBUG: Next page redirected ({raw_response.status_code}), last page reached.")
            return None
    except requests.RequestException as e:
        print(f"DEBUG: Request failed for next page: {e}")
        return None

    print(f"DEBUG: Next page found: {new_url}")
    return new_url


def run_spider(url=None, output_file='messages.json', max_pages=10):
    """
    Run the spider and save results to a JSON file

    Args:
        url: The URL to scrape messages from
        output_file: Path to save the scraped messages
        max_pages: Maximum number of pages to scrape
    """
    # Configure settings
    settings = get_project_settings()
    settings.update({
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
        'LOG_LEVEL': 'INFO',
        'FEED_FORMAT': 'jsonlines',  
        'FEED_URI': output_file,
        'FEED_EXPORT_ENCODING': 'utf-8',
        'ROBOTSTXT_OBEY': False,  
        'TELNETCONSOLE_ENABLED': False,
        'CONCURRENT_REQUESTS': 5,  
        'DOWNLOAD_DELAY': 1,  
        'AUTOTHROTTLE_ENABLED': True
    })

    if os.path.exists(output_file):
        os.remove(output_file)

    # Configure and run the spider - pass parameters as kwargs
    process = CrawlerProcess(settings)
    process.crawl(MessageSpider, url=url, max_pages=max_pages)
    process.start()

    # Load and display results
    if os.path.exists(output_file):
        # Read jsonlines format
        results = []
        with open(output_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():  # Skip empty lines
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue

        print(f"Successfully scraped {len(results)} messages from {url or 'default URL'}")
        return results
    else:
        print("No messages were scraped.")
        return []



def group_by_thread(jsonlines_file, output_file=None):
    """
    Read a flat jsonlines file produced by Scrapy and rewrite it as a
    structured JSON list grouped by thread.

    Output format:
    [
        {
            "thread_name": "...",
            "thread_url": "...",
            "messages": ["msg1", "msg2", ...]
        },
        ...
    ]

    Args:
        jsonlines_file (str): Path to the flat jsonlines input file.
        output_file (str): Path for the grouped JSON output.
                           Defaults to overwriting jsonlines_file.

    Returns:
        list: The grouped thread list.
    """
    if output_file is None:
        output_file = jsonlines_file

    threads = {}  # thread_url -> {"thread_name": ..., "messages": [...]}

    if not os.path.exists(jsonlines_file):
        return []

    with open(jsonlines_file, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue

            url = record.get('thread_url', '')
            name = record.get('thread_name', 'Unknown Thread')
            msg = record.get('message', '')

            if url not in threads:
                threads[url] = {'thread_name': name, 'thread_url': url, 'messages': [], '_seen': set()}
            if msg and msg not in threads[url]['_seen']:
                threads[url]['_seen'].add(msg)
                threads[url]['messages'].append(msg)

    # Strip internal dedup helper before serialising
    grouped = [{k: v for k, v in t.items() if k != '_seen'} for t in threads.values()]

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(grouped, f, ensure_ascii=False, indent=2)

    print(f"Grouped {len(grouped)} threads into {output_file}")
    return grouped


def link_gatherer():
    input_file = Path(__file__).parent.parent / 'data' / 'raw' / 'extracted_links.json'
    if os.path.exists(input_file):
        links = []
        seen_links = set()
        with open(input_file, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                link = json.loads(line.strip())['link']
                if link in seen_links:
                    continue
                seen_links.add(link)
                links.append(link)
        return links
    return []

async def run_spider_async(url, output_file='messages.json', max_pages=2):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, run_spider, url, output_file, max_pages)



def scrape_all_pages_recursively(links, output_file='messages.json', max_pages=10, resume=True):
    """
    Scrape all pages for the given links with progressive checkpoint-based saving.

    Completed thread URLs are recorded in a checkpoint file co-located with
    ``output_file`` so that an interrupted run can be resumed without
    re-scraping already-finished threads.

    Args:
        links (list): Thread URLs to scrape.
        output_file (str): Path for the raw jsonlines output.
        max_pages (int): Maximum pages to scrape per thread.
        resume (bool): If True (default), skip already-completed threads and
                       append to the existing output file.  Pass False to
                       start completely fresh.

    Returns:
        list: All scraped message records from the output file.
    """
    checkpoint_file = re.sub(r'\.json$', '_checkpoint.json', output_file)

    if resume:
        completed = load_checkpoint(checkpoint_file)
        pending_links = [l for l in links if l not in completed]
        if completed:
            print(f"Resuming scrape: {len(completed)} thread(s) already done, "
                  f"{len(pending_links)} remaining.")
    else:
        completed = set()
        pending_links = links
        if os.path.exists(checkpoint_file):
            os.remove(checkpoint_file)

    if not pending_links:
        print("All links have already been scraped. Nothing to do.")
        return _load_jsonlines(output_file)

    is_appending = resume and bool(completed)

    # Configure settings with max_pages
    settings = get_project_settings()
    settings.update({
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3',
        'LOG_LEVEL': 'INFO',  # Show more info for debugging
        'FEED_FORMAT': 'jsonlines',
        'FEED_URI': output_file,
        'FEED_EXPORT_ENCODING': 'utf-8',
        'FEED_EXPORT_APPEND': is_appending,  # Append when resuming a previous run
        'ROBOTSTXT_OBEY': False, # Not Illegal In This Site Btw, Thanks Normative Law; refer to https://www.golftutkusu.com/robots.txt and terms of service
        'TELNETCONSOLE_ENABLED': False,
        'CONCURRENT_REQUESTS': 5,
        'DOWNLOAD_DELAY': 1,
        'AUTOTHROTTLE_ENABLED': True
    })

    if not is_appending and os.path.exists(output_file):
        os.remove(output_file)

    # Run a single spider instance covering all pending links.
    # This avoids creating hundreds of separate spiders in one CrawlerProcess,
    # which would jam the Twisted reactor with synchronous requests.
    process = CrawlerProcess(settings)
    process.crawl(MessageSpider, urls=pending_links, max_pages=max_pages, checkpoint_file=checkpoint_file)
    process.start()

    return _load_jsonlines(output_file)


def _load_jsonlines(path):
    """Read a jsonlines file and return its records as a list."""
    results = []
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        results.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    return results

if __name__ == '__main__':
    # Example usage with explicit recursive scraping
    # target_url = 'https://www.golftutkusu.com/topic/18290-golf-7-yag-eksiltme-sorunu/'
    max_pages_to_scrape = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    resume_flag = '--no-resume' not in sys.argv  # pass --no-resume to start fresh
    _output = str(Path(__file__).parent.parent / 'data' / 'raw' / 'messages.json')

    links = link_gatherer()
    # Run the recursive spider (resumes from checkpoint by default)
    results = scrape_all_pages_recursively(links, _output, max_pages_to_scrape, resume=resume_flag)
    
    # Group flat jsonlines output into structured JSON by thread
    grouped = group_by_thread(_output)

    # Display results
    if grouped:
        total_msgs = sum(len(t['messages']) for t in grouped)
        print(f"\nSuccessfully scraped {total_msgs} messages across {len(grouped)} threads!")
        