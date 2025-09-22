# seo_analyzer.py
import requests
from bs4 import BeautifulSoup
import csv
import os
from urllib.parse import urljoin, urlparse
import time
from datetime import datetime

# === CONFIGURATION (User Input) ===
BASE_URL = input("Enter your WordPress site URL (e.g., https://yoursite.com): ").strip()
if not BASE_URL.startswith("http"):
    BASE_URL = "https://" + BASE_URL

OUTPUT_FILE = f"seo_report_{urlparse(BASE_URL).netloc}.csv"
HTML_FILE = f"seo_report_{urlparse(BASE_URL).netloc}.html"
PER_PAGE = 50
HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; SEO Analyzer/1.0)"
}
TIMEOUT = 10


# =====================
# SEO ANALYSIS FUNCTIONS
# =====================

def get_all_wordpress_urls(base_url):
    """Fetch all published posts and pages using WordPress REST API"""
    api_url = urljoin(base_url, "/wp-json/wp/v2/")
    endpoints = [urljoin(api_url, "posts"), urljoin(api_url, "pages")]
    urls = []

    for endpoint in endpoints:
        page = 1
        content_type = "post" if "posts" in endpoint else "page"
        print(f"🔍 Fetching {content_type}s from: {endpoint}")

        while True:
            try:
                params = {'per_page': PER_PAGE, 'page': page, 'status': 'publish'}
                response = requests.get(endpoint, params=params, headers=HEADERS, timeout=TIMEOUT)

                if response.status_code in [400, 404] and page > 1:
                    print(f"  → Pagination ended (status {response.status_code})")
                    break
                if not response.ok:
                    print(f"  ❌ {response.status_code} from {response.url}")
                    if page == 1:
                        print("     ⚠️ Check if REST API is blocked or site is down.")
                    break

                try:
                    items = response.json()
                    if not isinstance(items, list):
                        print(f"  ⚠️ Unexpected response format: {response.text[:200]}...")
                        break
                    if not items:
                        break
                except requests.exceptions.JSONDecodeError:
                    print(f"  ❌ Failed to parse JSON: {response.text[:200]}...")
                    if page == 1:
                        print("     🔐 Likely blocked by security plugin or redirect.")
                    break

                for item in items:
                    urls.append({
                        'title': item.get('title', {}).get('rendered', 'No Title'),
                        'url': item.get('link'),
                        'type': content_type
                    })

                print(f"  ✅ Page {page}: {len(items)} {content_type}(s)")
                page += 1
                time.sleep(0.1)

            except Exception as e:
                print(f"  ❌ Request failed: {e}")
                break

    return urls


def detect_seo_plugin(html):
    """Detect which SEO plugin is in use"""
    if 'yoast' in html.lower():
        return 'Yoast SEO'
    elif 'rank-math' in html.lower() or 'data-rank-math' in html.lower():
        return 'Rank Math'
    elif 'aioseo' in html.lower():
        return 'All in One SEO'
    return None


def analyze_html(html, url):
    """Analyze SEO elements in the HTML"""
    soup = BeautifulSoup(html, 'html.parser')
    base_domain = '/'.join(url.split('/')[:3])
    seo_plugin = detect_seo_plugin(html)

    report = {
        'title_tag': '',
        'h1_count': 0,
        'h1_text': '',
        'meta_description': 'Missing',
        'noindex': False,
        'has_og': False,
        'has_twitter': False,
        'missing_alt_count': 0,
        'missing_alt_images': [],
        'has_breadcrumb_schema': False,
        'has_breadcrumb_html': False,
        'issues': [],
        'issues_detail': [],
        'seo_plugin': seo_plugin
    }

    # === Page Title ===
    title_tag = soup.find('title')
    if title_tag:
        text = title_tag.get_text().strip()
        report['title_tag'] = text
        length = len(text)
        if length < 30:
            report['issues'].append("Title too short")
            report['issues_detail'].append(f"Title too short ({length} chars): {text}")
        elif length > 60:
            report['issues'].append("Title too long")
            report['issues_detail'].append(f"Title too long ({length} chars): {text}")
    else:
        report['issues'].append("Missing <title>")
        report['issues_detail'].append("Missing <title> tag")

    # === H1 ===
    h1_tags = soup.find_all('h1')
    report['h1_count'] = len(h1_tags)
    if h1_tags:
        report['h1_text'] = h1_tags[0].get_text().strip()
        if report['h1_count'] > 1:
            report['issues'].append("Multiple H1s")
            report['issues_detail'].append(f"Multiple H1s ({report['h1_count']}): {report['h1_text'][:50]}...")
    else:
        report['issues'].append("Missing H1")
        report['issues_detail'].append("No H1 tag found")

    # === Meta Description ===
    meta_desc = soup.find('meta', attrs={'name': 'description'})
    if meta_desc and meta_desc.get('content'):
        desc = meta_desc['content'].strip()
        report['meta_description'] = desc
        if len(desc) < 50:
            report['issues'].append("Meta desc too short")
            report['issues_detail'].append(f"Meta description too short ({len(desc)} chars)")
        elif len(desc) > 160:
            report['issues'].append("Meta desc too long")
            report['issues_detail'].append(f"Meta description too long ({len(desc)} chars)")
    else:
        report['issues'].append("Missing meta description")
        report['issues_detail'].append("Missing meta description tag")

    # === noindex ===
    if ('<meta name="robots" content="noindex' in html.lower() or
        'content="noindex' in html.lower()):
        report['noindex'] = True
        report['issues'].append("NOINDEX")
        report['issues_detail'].append("Page is set to NOINDEX")

    # === Open Graph & Twitter ===
    if soup.find('meta', property='og:title'):
        report['has_og'] = True
    else:
        report['issues'].append("Missing OG")
        report['issues_detail'].append("Missing Open Graph tags")

    if soup.find('meta', attrs={'name': 'twitter:card'}):
        report['has_twitter'] = True
    else:
        report['issues'].append("Missing Twitter Card")
        report['issues_detail'].append("Missing Twitter Card meta tag")

    # === Image Alt Text ===
    images = soup.find_all('img')
    missing_alt = []
    for img in images:
        src = img.get('src')
        alt = img.get('alt', '').strip()

        # Skip placeholders and spacers
        if not src:
            continue
        if 'data:image/gif;base64' in src or 'spacer' in src.lower():
            continue

        if not alt:
            img_url = urljoin(base_domain, src)
            missing_alt.append(img_url)

    report['missing_alt_count'] = len(missing_alt)
    report['missing_alt_images'] = missing_alt
    if missing_alt:
        report['issues'].append(f"{len(missing_alt)} images missing alt")
        for img_url in missing_alt[:5]:
            report['issues_detail'].append(f"Image missing alt: {img_url}")
        if len(missing_alt) > 5:
            report['issues_detail'].append(f"... and {len(missing_alt)-5} more")

    # === Breadcrumb Schema ===
    scripts = soup.find_all('script', type='application/ld+json')
    for script in scripts:
        try:
            if '"@type":"BreadcrumbList"' in script.string:
                report['has_breadcrumb_schema'] = True
                break
        except:
            continue
    if not report['has_breadcrumb_schema']:
        report['issues'].append("Missing breadcrumb schema")
        report['issues_detail'].append("Missing breadcrumb schema (JSON-LD)")

    # === Breadcrumb HTML ===
    breadcrumbs = soup.find_all(['nav'], string=lambda x: x and 'breadcrumb' in str(x).lower())
    breadcrumbs += soup.find_all(class_=lambda x: x and 'breadcrumb' in str(x).lower())
    if breadcrumbs:
        report['has_breadcrumb_html'] = True

    report['status'] = "OK" if not report['issues'] else "ISSUE"
    return report


def generate_html_report(results, base_url):
    """Generate a beautiful, self-contained HTML SEO report with smart tips"""
    total_pages = len(results)
    clean_pages = len([r for r in results if r['Issues Summary'] == 'OK'])
    has_h1_ok = len([r for r in results if 'Missing H1' not in r['Issues Detail']])
    title_good = len([r for r in results if 'Title too short' not in r['Issues Detail'] and 'Title too long' not in r['Issues Detail']])

    # Only count if meta desc exists AND is within 50–160 chars
    meta_good = 0
    for r in results:
        issues = r['Issues Detail']
        has_missing = 'Missing meta description tag' in issues
        has_short = 'Meta description too short' in issues
        has_long = 'Meta description too long' in issues
        if not has_missing and not has_short and not has_long and r['Meta Description'] != 'Missing':
            meta_good += 1

    og_good = len([r for r in results if 'Missing OG' not in r['Issues Detail']])
    twitter_good = len([r for r in results if 'Missing Twitter Card' not in r['Issues Detail']])
    schema_good = len([r for r in results if 'Missing breadcrumb schema' not in r['Issues Detail']])

    # Detect most used SEO plugin
    plugins = [r['SEO Plugin'] for r in results if r['SEO Plugin']]
    primary_plugin = max(set(plugins), key=plugins.count) if plugins else None

    # Sort by severity
    def severity(r):
        if 'noindex' in r['Issues Detail'].lower() or 'Missing H1' in r['Issues Detail']:
            return 2
        if 'OK' in r['Issues Summary']:
            return 0
        return 1

    results.sort(key=severity, reverse=True)

    def get_color(r):
        if 'noindex' in r['Issues Detail'].lower() or 'Missing H1' in r['Issues Detail']:
            return "#ffebee"
        if 'OK' in r['Issues Summary']:
            return "#f0f9f0"
        return "#fff8e1"

    # Start HTML
    html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <title>SEO Audit Report: {base_url}</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link href="https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap" rel="stylesheet">
    <script src="https://cdn.tailwindcss.com"></script>
    <style>
        body {{ font-family: 'Roboto', sans-serif; }}
        .hover-expand {{ cursor: pointer; }}
        .issue-list {{ padding-left: 20px; margin: 8px 0; font-size: 0.95em; }}
        .img-preview {{ max-width: 120px; max-height: 80px; object-fit: cover; border-radius: 4px; }}
        .hidden {{ display: none; }}
        .search-box input {{ width: 100%; padding: 10px; border: 1px solid #ccc; border-radius: 6px; }}
        .tip {{ font-size: 0.9em; color: #6b7280; margin-top: 4px; }}
        .code {{ background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-family: monospace; }}
    </style>
    <script>
        function toggleRow(id) {{ document.getElementById('details-'+id).classList.toggle('hidden'); }}
        function filterTable() {{
            const q = document.getElementById('search').value.toLowerCase();
            document.querySelectorAll('[data-search]').forEach(r => {{
                r.style.display = r.getAttribute('data-search').toLowerCase().includes(q) ? '' : 'none';
            }});
        }}
        function generateMetaSuggestion(topic) {{
            const input = prompt("Enter topic or keyword for this page:");
            if (input) {{
                const suggestion = `Discover everything about ${input} — expert insights and practical tips.`;
                alert("Suggested meta description:\\n\\n" + suggestion);
            }}
        }}
    </script>
</head>
<body class="bg-gray-50 text-gray-800">
    <div class="max-w-6xl mx-auto p-6">

        <!-- Header -->
        <h1 class="text-3xl font-bold text-center mb-2">SEO Audit Report</h1>
        <p class="text-center text-gray-600 mb-6">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M')} | Site: <strong>{base_url}</strong></p>

        <!-- Search -->
        <div class="search-box mb-4">
            <input type="text" id="search" placeholder="🔍 Filter by URL, issue, image..." onkeyup="filterTable()">
        </div>

        <!-- Stats -->
        <div class="grid grid-cols-2 md:grid-cols-4 gap-4 my-6 text-center">
            <div class="bg-white p-4 rounded shadow">
                <strong class="text-xl">{total_pages}</strong><br>
                <span class="text-sm text-gray-600">Pages Scanned</span>
            </div>
            <div class="bg-green-100 p-4 rounded shadow">
                <strong class="text-xl">{clean_pages}</strong><br>
                <span class="text-sm text-gray-600">Fully OK</span>
            </div>
            <div class="bg-yellow-100 p-4 rounded shadow">
                <strong class="text-xl">{len([r for r in results if r['Issues Summary'] != 'OK'])}</strong><br>
                <span class="text-sm text-gray-600">With Issues</span>
            </div>
            <div class="bg-red-100 p-4 rounded shadow">
                <strong class="text-xl">{sum(1 for r in results if 'noindex' in r['Issues Detail'].lower() or 'Missing H1' in r['Issues Detail'])}</strong><br>
                <span class="text-sm text-gray-600">Critical Issues</span>
            </div>
        </div>

        <!-- Table -->
        <table class="w-full border-collapse shadow-md bg-white">
            <thead class="bg-gray-100 text-left uppercase text-sm font-semibold">
                <tr>
                    <th class="py-3 px-4">Status</th>
                    <th class="py-3 px-4">Page Title</th>
                    <th class="py-3 px-4">Type</th>
                    <th class="py-3 px-4">Issues</th>
                </tr>
            </thead>
            <tbody>
"""

    # Add rows
    for idx, r in enumerate(results):
        bg = get_color(r)
        short_title = r['Title'][:30] + "..." if len(r['Title']) > 30 else r['Title']

        html += f"""
        <tr class="hover-expand" data-search="{r['URL']} {r['Issues Detail']}" onclick="toggleRow('{idx}')">
            <td class="py-3 px-4" style="background-color: {bg}">
                <strong>
                    {'🟢 OK' if r['Issues Summary']=='OK' else '🔴 Critical' if 'noindex' in r['Issues Detail'].lower() or 'Missing H1' in r['Issues Detail'] else '🟡 Warning'}
                </strong>
            </td>
            <td class="py-3 px-4 font-medium">{short_title}</td>
            <td class="py-3 px-4 text-sm text-gray-600">{r['Type'].upper()}</td>
            <td class="py-3 px-4 text-sm">{r['Issues Summary']}</td>
        </tr>
        <tr id="details-{idx}" class="hidden border-t">
            <td colspan="4" class="p-4 bg-gray-50">
                <div class="space-y-3">
                    <p><strong>URL:</strong> <a href="{r['URL']}" target="_blank" class="text-blue-600 hover:underline">{r['URL']}</a></p>
                    <p><strong>Full Issues:</strong></p>
                    <ul class="issue-list">
        """

        for issue in r['Issues Detail'].split(' | '):
            html += f"<li>• {issue}</li>"

        if r['Missing Alt Image URLs']:
            html += """
                <p><strong>Images Missing Alt Text:</strong></p>
                <div class="flex flex-wrap gap-3 mt-2">
            """
            for img in r['Missing Alt Image URLs'].split('; ')[:10]:
                html += f'''
                    <div class="text-center">
                        <img src="{img}" alt="Missing alt" class="img-preview border">
                        <a href="{img}" target="_blank" class="text-xs text-gray-500 hover:text-blue-600">View</a>
                    </div>
                '''
            if len(r['Missing Alt Image URLs'].split('; ')) > 10:
                html += f"<p class='text-xs'>... and {len(r['Missing Alt Image URLs'].split('; ')) - 10} more</p>"
            html += "</div>"

        html += """
                </div>
            </td>
        </tr>
        """

    html += """
            </tbody>
        </table>

        <!-- What's Working Well -->
        <div class="mt-12 p-6 bg-green-50 border-l-4 border-green-400">
            <h2 class="text-2xl font-bold text-gray-800 mb-4">✅ What’s Working Well</h2>
            <p class="text-gray-700 mb-4">These best practices are being followed across your site:</p>
            <ul class="space-y-2 text-gray-700">
    """

    if has_h1_ok > 0:
        html += f"<li>🟢 {has_h1_ok}/{total_pages} pages include an H1 tag</li>"
    else:
        html += "<li>🔴 All pages should have one H1 — it helps search engines understand your content</li>"

    if title_good > 0:
        html += f"<li>🟢 {title_good}/{total_pages} pages have title tags within optimal length (50–60 characters)</li>"
    else:
        html += "<li>🟡 Consider optimizing titles — Google typically displays ~60 characters</li>"

    if meta_good > 0:
        html += f"<li>🟢 {meta_good}/{total_pages} pages have complete and well-sized meta descriptions (50–160 chars)</li>"
    else:
        html += "<li>⚠️ No pages have proper meta descriptions — they're missing or incorrectly sized</li>"

    if og_good > 0:
        html += f"<li>🟢 {og_good}/{total_pages} pages include Open Graph tags for social sharing</li>"
    else:
        html += "<li>💡 Add OG tags so links look great when shared on Facebook, LinkedIn, etc.</li>"

    if twitter_good > 0:
        html += f"<li>🟢 {twitter_good}/{total_pages} pages support Twitter Cards</li>"
    else:
        html += "<li>❌ None of your pages support Twitter Cards — missed engagement opportunity</li>"

    if schema_good > 0:
        html += f"<li>🟢 {schema_good}/{total_pages} pages include breadcrumb schema (JSON-LD)</li>"
    else:
        html += "<li>🚫 Breadcrumb schema missing site-wide — hurts rich snippets and navigation clarity</li>"

    html += """
            </ul>
            <p class="text-gray-600 text-sm mt-4"><strong>Note:</strong> A “good” element means it exists AND meets best practice standards.</p>
        </div>

        <!-- Quick Wins -->
        <div class="mt-8 p-6 bg-blue-50 border-l-4 border-blue-400">
            <h2 class="text-2xl font-bold text-gray-800 mb-4">⚡ Quick Wins (<2 min each)</h2>
            <ul class="space-y-2 text-gray-700">
                <li>✅ Add missing meta descriptions using your SEO plugin</li>
                <li>✅ Set <span class="code">alt=""</span> on decorative images</li>
                <li>✅ Enable Twitter Card via your SEO plugin settings</li>
                <li><button onclick="generateMetaSuggestion()" class="text-blue-600 underline">💡 Generate Meta Description Suggestion</button></li>
            </ul>
        </div>

        <!-- Next Steps -->
        <div class="mt-8 p-6 bg-indigo-50 border-l-4 border-indigo-400">
            <h2 class="text-2xl font-bold text-gray-800 mb-4">📋 Your Next Steps</h2>
            <ol class="space-y-2 text-gray-700">
                <li>1. Install Rank Math or Yoast SEO (if not already)</li>
                <li>2. Fix missing H1 on critical pages</li>
                <li>3. Write meta descriptions for top 5 traffic pages</li>
                <li>4. Add Open Graph image to homepage</li>
                <li>5. Re-run this audit in 1 week</li>
            </ol>
            <p class="text-sm text-gray-500 mt-4">Tip: Share this list with your developer or writer!</p>
        </div>

        <p class="text-center mt-8 text-sm text-gray-500">
            Custom SEO Analyzer for WordPress by Victoria with the help of Qwen
        </p>
    </div>
</body>
</html>
"""

    with open(HTML_FILE, 'w', encoding='utf-8') as f:
        f.write(html)
    return HTML_FILE


# =====================
# MAIN FUNCTION
# =====================

def main():
    print(f"\n🔍 Starting SEO audit for: {BASE_URL}")
    print("Fetching all posts and pages...\n")

    pages = get_all_wordpress_urls(BASE_URL)

    if not pages:
        print("❌ No pages found. Check your URL or site accessibility.")
        return

    print(f"✅ Found {len(pages)} pages. Analyzing...\n")

    results = []
    for i, page in enumerate(pages, 1):
        print(f"[{i}/{len(pages)}] Checking: {page['url']}")
        try:
            response = requests.get(page['url'], headers=HEADERS, timeout=TIMEOUT)
            response.raise_for_status()
            report = analyze_html(response.text, page['url'])
        except Exception as e:
            report = {
                'title_tag': '',
                'h1_count': 0,
                'h1_text': '',
                'meta_description': '',
                'noindex': False,
                'has_og': False,
                'has_twitter': False,
                'missing_alt_count': 0,
                'missing_alt_images': [],
                'has_breadcrumb_schema': False,
                'has_breadcrumb_html': False,
                'issues': [f"Failed to load: {str(e)}"],
                'issues_detail': [f"Failed to load: {str(e)}"],
                'seo_plugin': None
            }

        results.append({
            'Type': page['type'],
            'Title': page['title'],
            'URL': page['url'],
            'Page Title': report['title_tag'],
            'H1 Count': report['h1_count'],
            'H1 Text': report['h1_text'],
            'Meta Description': report['meta_description'],
            'NoIndex': 'Yes' if report['noindex'] else 'No',
            'OG Tags': 'Yes' if report['has_og'] else 'No',
            'Twitter Card': 'Yes' if report['has_twitter'] else 'No',
            'Missing Alt Count': report['missing_alt_count'],
            'Missing Alt Image URLs': '; '.join(report['missing_alt_images']),
            'Breadcrumb Schema': 'Yes' if report['has_breadcrumb_schema'] else 'No',
            'Breadcrumb HTML': 'Yes' if report['has_breadcrumb_html'] else 'No',
            'SEO Plugin': report['seo_plugin'] or 'Unknown',
            'Issues Summary': '; '.join(report['issues']) if report['issues'] else 'OK',
            'Issues Detail': ' | '.join(report['issues_detail'])
        })

    # Save CSV
    try:
        keys = results[0].keys() if results else ['Type', 'Title', 'URL']
        with open(OUTPUT_FILE, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=keys)
            writer.writeheader()
            writer.writerows(results)
        print(f"📊 CSV report saved: {OUTPUT_FILE}")
    except Exception as e:
        print(f"❌ Failed to save CSV: {e}")

    # Generate HTML
    html_file = generate_html_report(results, BASE_URL)
    print(f"\n🎨 HTML report generated: {html_file}")

    # Open in browser
    import webbrowser
    webbrowser.open(f"file://{os.path.abspath(html_file)}")

    # Summary
    issues = [r for r in results if r['Issues Summary'] != 'OK']
    critical = sum(1 for r in results if 'noindex' in r['Issues Detail'].lower() or 'Missing H1' in r['Issues Detail'])
    print(f"\n🎉 Audit complete!")
    print(f"📊 Total pages: {len(results)}")
    print(f"🔴 Critical: {critical}")
    print(f"🟡 Warnings: {len(issues) - critical}")
    print(f"🟢 Clean: {len(results) - len(issues)}")


if __name__ == "__main__":
    main()