import requests
from bs4 import BeautifulSoup

def get_token_info_from_tonviewer(address):
    try:
        url = f"https://tonviewer.com/{address}"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")

        # Scrape title
        title_tag = soup.find("h1")
        title = title_tag.text.strip() if title_tag else "Unknown Token"

        # Scrape supply and holders
        supply_tag = soup.find("div", string="Total supply")
        holders_tag = soup.find("div", string="Holders")

        supply_value = supply_tag.find_next_sibling("div").text if supply_tag else "N/A"
        holders_value = holders_tag.find_next_sibling("div").text if holders_tag else "N/A"

        # Detect if token is verified
        verified = "✅" if "Verified" in response.text else "❌"

        return {
            "title": title,
            "supply": supply_value,
            "holders": holders_value,
            "verified": verified
        }

    except Exception as e:
        print(f"[TonViewer Error] {e}")
        return None
