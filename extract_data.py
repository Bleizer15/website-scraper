import requests
from bs4 import BeautifulSoup
import csv
from datetime import datetime

def extract_product_data(url):
    response = requests.get(url)
    if response.status_code != 200:
        print(f"Failed to retrieve data: {response.status_code}")
        return []

    soup = BeautifulSoup(response.content, 'html.parser')
    products = []

    # Assuming the product name and price are in <h2> and <span> tags respectively
    for item in soup.find_all('div', class_='product-item'):
        product_name = item.find('h2').text.strip()
        price = item.find('span', class_='price').text.strip()
        products.append({'name': product_name, 'price': price})

    return products

def save_data_to_csv(data):
    filename = f"products_{datetime.now().strftime('%Y-%m')}.csv"
    with open(filename, mode='w', newline='', encoding='utf-8') as file:
        writer = csv.DictWriter(file, fieldnames=['name', 'price'])
        writer.writeheader()
        for product in data:
            writer.writerow(product)
    return filename

def main():
    url = 'https://example.com/products'  # Replace with the actual URL
    products = extract_product_data(url)
    filename = save_data_to_csv(products)
    print(f"Data saved to {filename}")

if __name__ == '__main__':
    main()
