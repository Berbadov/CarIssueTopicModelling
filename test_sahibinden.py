import sys
from curl_cffi import requests
from bs4 import BeautifulSoup

url = "https://www.sahibinden.com/listing/vasita-otomobil-volkswagen-sahibinden-2017-model-full-yetkili-servis-bakimli-1312290807/detail"
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"
}
try:
    response = requests.get(url, impersonate="chrome120", headers=headers)
    
    if response.status_code == 200:
        soup = BeautifulSoup(response.text, 'html.parser')
        info_list = soup.find('ul', class_='classifiedInfoList')
        
        if info_list:
            print("--- Technical Details ---")
            for li in info_list.find_all('li'):
                # The label is usually in a <strong> or span, value in span
                strong = li.find('strong')
                span = li.find('span')
                if strong and span:
                    key = strong.text.strip()
                    val = span.text.strip()
                    print(f"{key}: {val}")
        else:
            print("Could not find classifiedInfoList. Might be blocked or structure changed.")
            print(response.text[:500])
    else:
        print(f"Failed with status code: {response.status_code}")
except Exception as e:
    print(f"Error: {e}")
