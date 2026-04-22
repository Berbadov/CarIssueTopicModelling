import os
from bs4 import BeautifulSoup

file_path = r"data/raw/Volkswagen _ Golf _ 1.4 TSI _ Highline _ 2016VW GOLF HİGHLİNE-ORJ. 79.000KM_1.4TSİ"

try:
    with open(file_path, 'r', encoding='utf-8') as f:
        html_content = f.read()

    soup = BeautifulSoup(html_content, 'html.parser')
    info_list = soup.find('ul', class_='classifiedInfoList')

    if info_list:
        print("--- Technical Details ---")
        for li in info_list.find_all('li'):
            strong = li.find('strong')
            span = li.find('span')
            if strong and span:
                key = strong.get_text(strip=True)
                val = span.get_text(strip=True)
                print(f"{key}: {val}")
    else:
        print("Could not find classifiedInfoList in the HTML.")
except Exception as e:
    print(f"Error parsing file: {e}")
