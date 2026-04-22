import json
import os
import pathlib
import re
import sys
from os import link, path

import requests
import scrapy
from scrapy.crawler import CrawlerProcess
from scrapy.linkextractors import LinkExtractor as ScrapyLinkExtractor
from scrapy.utils.project import get_project_settings

# NOTES
# Need to some filtering, some links are duplicated as '/latest/' and there are some other issues
# In the link, given url includes itself several times.


# Next page extractor is also needed, as there are multiple pages in the forum,
# and we need to extract links from all pages, not just the first one.
# We can use the same ScrapyLinkExtractor to find the next page link and follow it until
# there are no more pages left. This way we can ensure that we are extracting links from all
# pages of the forum, not just the first one. DONE


class LinkExtractor(scrapy.Spider):
    name = "link_extractor"

    def __init__(self, url=None, *args, **kwargs):
        super(LinkExtractor, self).__init__(*args, **kwargs)
        self.start_urls = (
            [url]
            if url
            else ["https://www.golftutkusu.com/forum/446-golf-7-sorunlar-ve-cozumleri/"]
        )
        self.link_extractor = ScrapyLinkExtractor(
            allow=["/forum/", "/topic/"],
            deny=[
                r"/#top",
                r"/latest",
                r"/login/",
                r"/register/",
                r"/profile/",
                r"/misc/",
                r"/help/",
                r"/page/",
                r"/\?.*",
            ],
        )

        self.visited_urls = set()
        self.page_limit = (
            int(sys.argv[1]) if len(sys.argv) > 1 else 99
        )  # take it as an argument otherwise 99
        self.pages_crawled = 0

    def parse(self, response):
        # extracted_links = []
        links = self.link_extractor.extract_links(response)

        filtered_links = [
            link
            for link in links
            if link.url not in response.url
            and not re.search(r".*forum-kurallari.*", link.url)
        ]
        for link in filtered_links:
            self.visited_urls.add(link.url)
            yield {"link": link.url}

        next_page = next_page_finder(response.url)
        if (
            next_page
            and self.pages_crawled + 1 < self.page_limit
            and not next_page in self.visited_urls
        ):
            self.pages_crawled += 1
            self.visited_urls.add(next_page)
            yield scrapy.Request(url=next_page, callback=self.parse)


def run_spider(url=None, output_file="extracted_links.json"):

    settings = get_project_settings()
    settings.update(
        {
            "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3",
            "LOG_LEVEL": "INFO",
            "FEED_FORMAT": "jsonlines",
            "FEED_URI": output_file,
            "FEED_EXPORT_ENCODING": "utf-8",
            "ROBOTSTXT_OBEY": False,  # Turbo illegal, change before publishing
            "CONCURRENT_REQUESTS": 16,
            "DOWNLOAD_DELAY": 0.5,
            "AUTOTHROTTLE_ENABLED": True,
            "AUTOTHROTTLE_START_DELAY": 1,
            "AUTOTHROTTLE_MAX_DELAY": 3,
            "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        }
    )

    process = CrawlerProcess(settings)
    process.crawl(LinkExtractor, url=url)
    process.start()

    if os.path.exists(output_file):
        results = []
        with open(output_file, "r", encoding="utf-8") as f:
            for line in f:
                if line == url + "\n":  # Skip the line that contains the URL
                    continue
                if line.strip():  # Ensure we skip empty lines
                    try:
                        results.append(json.loads(line.strip()))
                    except json.JSONDecodeError as e:
                        print(f"Error decoding JSON line: {e}")

    return results


def next_page_finder(curr_url):
    """
    Extract the next page URL by incrementing the page number.

    Note: No explicit request validation needed since the forum returns
    a 400 error and redirects to page 99 (max pages), and we track
    visited URLs to prevent revisiting pages.
    """
    if not curr_url or not curr_url.strip():
        return None

    curr_url = curr_url.rstrip("/")
    match = re.search(r"/page/(\d+)/?$", curr_url)

    if match:
        # Page number exists - increment it
        curr_page = int(match.group(1))
        next_page = curr_page + 1
        next_page_url = re.sub(r"/page/\d+/?$", f"/page/{next_page}/", curr_url)
        return next_page_url
    else:
        # First page - append /page/2/ to start pagination
        return curr_url + "/page/2/"


if __name__ == "__main__":
    url = "https://www.golftutkusu.com/forum/446-golf-7-sorunlar-ve-cozumleri/"
    output_file = str(
        pathlib.Path(__file__).parent.parent / "data" / "raw" / "extracted_links.json"
    )

    extracted_links = run_spider(url, output_file)
    print(extracted_links)
