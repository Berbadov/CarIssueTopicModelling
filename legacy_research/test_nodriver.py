import asyncio
import nodriver as uc
from bs4 import BeautifulSoup

async def scrape_sahibinden(url):
    print("Starting browser...")
    # Open browser
    browser = await uc.start(
        headless=True,
        browser_args=["--disable-blink-features=AutomationControlled"]
    )
    
    print(f"Navigating to {url}...")
    page = await browser.get(url)
    
    # Wait a bit for cloudflare or load
    await asyncio.sleep(5)
    
    # Get HTML content
    html = await page.get_content()
    
    soup = BeautifulSoup(html, 'html.parser')
    
    # Check if we hit a captcha or block
    title = soup.title.string if soup.title else ""
    print(f"Page Title: {title}")
    
    info_list = soup.find('ul', class_='classifiedInfoList')
    
    if info_list:
        print("\n--- Technical Details ---")
        for li in info_list.find_all('li'):
            strong = li.find('strong')
            span = li.find('span')
            if strong and span:
                key = strong.text.strip()
                val = span.text.strip()
                print(f"{key}: {val}")
    else:
        print("\nCould not find the technical details section. Might be blocked or the element changed.")
        print(html[:1000])

    await browser.stop()

if __name__ == '__main__':
    url = "https://www.sahibinden.com/listing/vasita-otomobil-volkswagen-sahibinden-2017-model-full-yetkili-servis-bakimli-1312290807/detail"
    asyncio.run(scrape_sahibinden(url))
