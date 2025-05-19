# 1688.com and Taobao.com Product Scraper for WooCommerce

A fully automated scraper that extracts product data from 1688.com and Taobao.com, translates Chinese text to English, and formats the data for WooCommerce import.

## Features

- Fully automated scraping with no manual intervention required
- Supports both 1688.com and Taobao.com
- Automatic login handling with cookie persistence
- Captcha bypass using multiple methods
- Concurrent processing for faster scraping
- Automatic Chinese to English translation
- Image deduplication
- WooCommerce-compatible CSV output
- Detailed logging

## Requirements

- Python 3.8 or higher
- Chrome browser installed
- Internet connection
- (Optional) Anti-Captcha API key for better captcha solving

## Installation

1. Clone this repository:
```bash
git clone <repository-url>
cd <repository-directory>
```

2. Install required packages:
```bash
pip install -r requirements.txt
```

3. (Optional) Set up Anti-Captcha API key:
Create a `.env` file in the project directory and add:
```
ANTICAPTCHA_KEY=your_api_key_here
```

## Usage

1. Create a `urls.txt` file with product URLs to scrape (one per line):
```
https://detail.1688.com/offer/123456789.html
https://item.taobao.com/item.htm?id=123456789
```

2. Run the scraper:
```bash
python final_product_scraper.py
```

3. The script will:
   - Create necessary directories (product_images, cookies, logs)
   - Handle login and captchas automatically
   - Scrape product data
   - Translate Chinese text to English
   - Download and deduplicate images
   - Save results to `woocommerce_products.csv`

## Output

The script generates:
- `woocommerce_products.csv`: WooCommerce-compatible product data
- `product_images/`: Directory containing downloaded product images
- `logs/`: Directory containing detailed logs
- `cookies/`: Directory containing saved cookies for faster subsequent runs

## CSV Format

The output CSV includes:
- SKU
- Name
- Regular price
- Description
- Short description
- Images
- Stock status
- Product type
- Categories
- Original URL
- Variations
- Shipping info
- Seller info

## Notes

- The script uses undetected-chromedriver to avoid detection
- Cloudflare protection is automatically bypassed
- Multiple translation services are used as fallbacks
- Images are deduplicated using content hashing
- Concurrent processing improves speed but may trigger rate limits

## Troubleshooting

1. If you encounter login issues:
   - Check the logs in the `logs` directory
   - Try clearing the `cookies` directory
   - Ensure your internet connection is stable

2. If captchas are not being solved:
   - Consider getting an Anti-Captcha API key
   - Check the logs for specific captcha errors
   - Try reducing the number of concurrent workers

3. If translation fails:
   - Check your internet connection
   - Try using a VPN if services are blocked
   - Check the logs for specific translation errors

## License

This project is licensed under the MIT License - see the LICENSE file for details. 