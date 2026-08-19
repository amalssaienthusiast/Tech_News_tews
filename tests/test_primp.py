import asyncio
import primp
import urllib.parse
from bs4 import BeautifulSoup

from src.utils.primp_profiles import get_chrome_profile
client = primp.Client(impersonate=get_chrome_profile())
response = client.post("https://lite.duckduckgo.com/lite/", data={"q": "technology news", "kl": ""})

print(response.status_code)
html = response.text
print("Length:", len(html))

soup = BeautifulSoup(html, 'html.parser')
results = soup.find_all('tr')
for r in results:
    title_elem = r.find('a', class_='result-url')
    if title_elem:
        print(title_elem.text.strip())
        print(title_elem.get('href'))

