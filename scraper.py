import requests
from bs4 import BeautifulSoup
import pandas as pd

def get_product_info(url):
    try:
        response = requests.get(url)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Error fetching the webpage: {e}")
        return []

    soup = BeautifulSoup(response.text, 'html.parser')
    products = []

    # Assuming product information is within <div class="product">
    for product in soup.find_all('div', class_='product'):
        if not product:
            continue
        
        name = product.find('h2').text.strip()
        
        # Find the largest package/volume size and its price
        prices = product.find_all('span', class_='price')
        if prices:
            max_price = max(prices, key=lambda x: float(x.text.replace(',', '').replace('.', '')))
            price = max_price.text.strip()
        else:
            price = 'N/A'
        
        products.append({'Name': name, 'Price': price})

    return products

def save_to_excel(data, filename='extracted_data.xlsx'):
    df = pd.DataFrame(data)
    try:
        df.to_excel(filename, index=False)
        print(f"Data saved to {filename}")
    except Exception as e:
        print(f"Error saving data to Excel: {e}")

if __name__ == '__main__':
    url = 'https://www.myagrar.de/pflanzenschutzmittel/'
    data = get_product_info(url)
    save_to_excel(data)
