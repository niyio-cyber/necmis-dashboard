#!/usr/bin/env python3
"""
NECMIS Scraper - Phase 2 (HTML Parser)
======================================
Uses BeautifulSoup to parse actual HTML from DOT sites.
"""

import json
import hashlib
import re
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

try:
    import requests
    import feedparser
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing dependency: {e}")
    raise


# =============================================================================
# CONFIGURATION
# =============================================================================

STATES = ['VT', 'NH', 'ME', 'MA', 'NY', 'RI', 'CT', 'PA']

RSS_FEEDS = {
    'VTDigger': {'url': 'https://vtdigger.org/feed/', 'state': 'VT'},
    'Union Leader': {'url': 'https://www.unionleader.com/search/?f=rss&t=article&c=news/business&l=25&s=start_time&sd=desc', 'state': 'NH'},
    'Portland Press Herald': {'url': 'https://www.pressherald.com/feed/', 'state': 'ME'},
    'Bangor Daily News': {'url': 'https://bangordailynews.com/feed/', 'state': 'ME'},
    'InDepthNH': {'url': 'https://indepthnh.org/feed/', 'state': 'NH'},
    'Valley News': {'url': 'https://www.vnews.com/feed/articles/rss', 'state': 'VT'},
    'MassLive': {'url': 'https://www.masslive.com/arc/outboundfeeds/rss/?outputType=xml', 'state': 'MA'},
    'Times Union': {'url': 'https://www.timesunion.com/search/?action=search&channel=news&inlineContent=1&searchindex=solr&query=construction&sort=date&output=rss', 'state': 'NY'},
    'Providence Journal': {'url': 'https://www.providencejournal.com/arcio/rss/', 'state': 'RI'},
    'Hartford Courant': {'url': 'https://www.courant.com/arcio/rss/', 'state': 'CT'}
}

DOT_SOURCES = {
    'MA': {'name': 'MassDOT', 'portal_url': 'https://hwy.massdot.state.ma.us/webapps/const/statusReport.asp', 'parser': 'active'},
    'ME': {'name': 'MaineDOT', 'portal_url': 'https://www.maine.gov/dot/doing-business/bid-opportunities', 'parser': 'stub'},
    'NH': {'name': 'NHDOT', 'portal_url': 'https://www.dot.nh.gov/doing-business-nhdot/contractors/invitation-bid', 'parser': 'stub'},
    'VT': {'name': 'VTrans', 'portal_url': 'https://vtrans.vermont.gov/contract-admin/bids-requests/construction-contracting', 'parser': 'stub'},
    'NY': {'name': 'NYSDOT', 'portal_url': 'https://www.dot.ny.gov/doing-business/opportunities/const-highway', 'parser': 'stub'},
    'RI': {'name': 'RIDOT', 'portal_url': 'https://www.dot.ri.gov/about/current_projects.php', 'parser': 'stub'},
    'CT': {'name': 'CTDOT', 'portal_url': 'https://portal.ct.gov/DOT/Doing-Business/Contractor-Information', 'parser': 'stub'},
    'PA': {'name': 'PennDOT', 'portal_url': 'https://www.penndot.pa.gov/business/Letting/Pages/default.aspx', 'parser': 'stub'}
}

CONSTRUCTION_KEYWORDS = {
    'high_priority': ['highway', 'bridge', 'DOT', 'bid', 'letting', 'RFP', 'contract award', 'paving', 'resurfacing', 'infrastructure', 'IIJA', 'federal grant'],
    'medium_priority': ['construction', 'road', 'pavement', 'asphalt', 'concrete', 'aggregate', 'gravel', 'development', 'permit', 'municipal'],
    'business_line_keywords': {
        'highway': ['highway', 'road', 'interstate', 'route', 'bridge', 'DOT', 'transportation'],
        'hma': ['asphalt', 'paving', 'resurfacing', 'overlay', 'milling', 'HMA', 'hot mix', 'surfacing', 'pavement'],
        'aggregates': ['aggregate', 'gravel', 'sand', 'stone', 'quarry'],
        'ready_mix': ['concrete', 'ready-mix', 'cement', 'bridge deck'],
        'liquid_asphalt': ['liquid asphalt', 'bitumen', 'emulsion']
    }
}


# =============================================================================
# HELPERS
# =============================================================================

def generate_id(text: str) -> str:
    return hashlib.md5(text.encode()).hexdigest()[:12]

def get_priority(text: str) -> str:
    text_lower = text.lower()
    if any(kw.lower() in text_lower for kw in CONSTRUCTION_KEYWORDS['high_priority']):
        return 'high'
    if any(kw.lower() in text_lower for kw in CONSTRUCTION_KEYWORDS['medium_priority']):
        return 'medium'
    return 'low'

def get_business_lines(text: str) -> List[str]:
    text_lower = text.lower()
    lines = []
    for line, keywords in CONSTRUCTION_KEYWORDS['business_line_keywords'].items():
        if any(kw.lower() in text_lower for kw in keywords):
            lines.append(line)
    return lines if lines else ['highway']

def is_construction_relevant(text: str) -> bool:
    text_lower = text.lower()
    all_kw = CONSTRUCTION_KEYWORDS['high_priority'] + CONSTRUCTION_KEYWORDS['medium_priority']
    return any(kw.lower() in text_lower for kw in all_kw)

def format_currency(amount) -> Optional[str]:
    if amount is None:
        return None
    if amount >= 1000000000:
        return f"${amount / 1000000000:.1f}B"
    elif amount >= 1000000:
        return f"${amount / 1000000:.1f}M"
    elif amount >= 1000:
        return f"${amount / 1000:.0f}K"
    return f"${amount:,.0f}"

def parse_currency(text: str) -> Optional[float]:
    if not text:
        return None
    cleaned = re.sub(r'[,$]', '', text.strip())
    try:
        return float(cleaned)
    except ValueError:
        return None


# =============================================================================
# MASSDOT PARSER (HTML-based)
# =============================================================================

def parse_massdot() -> List[Dict]:
    """
    Parse MassDOT using BeautifulSoup for HTML parsing.
    Extract all dollar amounts found on the page.
    """
    url = DOT_SOURCES['MA']['portal_url']
    lettings = []
    
    try:
        print(f"    🔍 Fetching MassDOT...")
        response = requests.get(url, timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        response.raise_for_status()
        html = response.text
        
        print(f"    📄 Got {len(html)} bytes")
        
        # Parse with BeautifulSoup
        soup = BeautifulSoup(html, 'html.parser')
        
        # Get all text content
        text = soup.get_text(separator='\n')
        
        # Debug: show sample of text
        sample = text[:1000].replace('\n', ' | ')
        print(f"    🔬 Text sample: {sample[:300]}...")
        
        # Find ALL dollar amounts on the page (pattern: $X,XXX,XXX.XX)
        dollar_pattern = r'\$[\d,]+(?:\.\d{2})?'
        all_dollars = re.findall(dollar_pattern, text)
        
        # Filter for realistic project values ($100K to $500M)
        project_values = []
        for d in all_dollars:
            val = parse_currency(d.replace('$', ''))
            if val and 100000 <= val <= 500000000:  # $100K to $500M
                project_values.append(val)
        
        print(f"    💰 Found {len(all_dollars)} dollar amounts, {len(project_values)} project-sized")
        
        # Also try to find project-related text blocks
        # Look for tables
        tables = soup.find_all('table')
        print(f"    📋 Found {len(tables)} tables")
        
        # Try to extract from table rows
        rows_with_money = []
        for table in tables:
            for row in table.find_all('tr'):
                row_text = row.get_text(separator=' ')
                dollars_in_row = re.findall(dollar_pattern, row_text)
                for d in dollars_in_row:
                    val = parse_currency(d.replace('$', ''))
                    if val and 100000 <= val <= 500000000:
                        rows_with_money.append({
                            'text': row_text[:200],
                            'value': val
                        })
        
        print(f"    📊 Found {len(rows_with_money)} table rows with project values")
        
        # Also look for labeled fields using various patterns
        patterns = [
            # HTML bold/italic tags
            (r'<b>Location:</b>\s*<i>([^<]+)</i>', 'location'),
            (r'<b>Description:</b>\s*<i>([^<]+)</i>', 'description'),
            (r'<b>Project Value:</b>\s*\$([0-9,]+\.?\d*)', 'value'),
            (r'<b>Project Number:</b>\s*(\d+)', 'project_num'),
            # Plain text patterns
            (r'Location:\s*([A-Z][A-Za-z\s\-]+)', 'location'),
            (r'Project Value:\s*\$([0-9,]+\.?\d*)', 'value'),
            (r'Project Number:\s*(\d+)', 'project_num'),
            # Table cell patterns
            (r'>\s*([A-Z]{2,}(?:\s+[A-Z]+)*)\s*<', 'location'),  # All caps town names
        ]
        
        extracted = {'location': [], 'description': [], 'value': [], 'project_num': []}
        for pattern, field in patterns:
            matches = re.findall(pattern, html, re.IGNORECASE)
            if matches:
                extracted[field].extend(matches)
                print(f"    Pattern '{field}': found {len(matches)}")
        
        # Build projects from extracted data or table rows
        if rows_with_money:
            print(f"    📦 Building from {len(rows_with_money)} table rows...")
            for i, row in enumerate(rows_with_money[:50]):
                # Extract location from row text (first all-caps word)
                loc_match = re.search(r'\b([A-Z]{3,}(?:\s+[A-Z]+)*)\b', row['text'])
                location = loc_match.group(1) if loc_match else None
                
                desc = row['text'][:150].strip()
                
                letting = {
                    'id': generate_id(f"MA-{i}-{desc[:25]}"),
                    'state': 'MA',
                    'project_id': None,
                    'description': desc,
                    'cost_low': int(row['value']),
                    'cost_high': int(row['value']),
                    'cost_display': format_currency(row['value']),
                    'ad_date': None,
                    'let_date': None,
                    'project_type': None,
                    'county': location,
                    'url': url,
                    'source': 'MassDOT',
                    'business_lines': get_business_lines(desc)
                }
                lettings.append(letting)
        
        elif project_values:
            # Create basic entries from dollar amounts
            print(f"    📦 Building from {len(project_values)} dollar amounts...")
            for i, val in enumerate(project_values[:50]):
                letting = {
                    'id': generate_id(f"MA-{i}-{val}"),
                    'state': 'MA',
                    'project_id': None,
                    'description': f"MassDOT Highway Project #{i+1}",
                    'cost_low': int(val),
                    'cost_high': int(val),
                    'cost_display': format_currency(val),
                    'ad_date': None,
                    'let_date': None,
                    'project_type': 'Highway Construction',
                    'county': None,
                    'url': url,
                    'source': 'MassDOT',
                    'business_lines': ['highway']
                }
                lettings.append(letting)
        
        if lettings:
            total = sum(l.get('cost_low') or 0 for l in lettings)
            print(f"    ✓ {len(lettings)} projects, {format_currency(total)} total pipeline")
        else:
            print(f"    ⚠ No projects parsed")
            lettings.append(create_portal_stub('MA'))
            
    except Exception as e:
        print(f"    ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        lettings.append(create_portal_stub('MA'))
    
    return lettings


def create_portal_stub(state: str) -> Dict:
    cfg = DOT_SOURCES[state]
    return {
        'id': generate_id(f"{state}-portal"),
        'state': state,
        'project_id': None,
        'description': f"{cfg['name']} Bid Schedule - Visit portal for current lettings",
        'cost_low': None,
        'cost_high': None,
        'cost_display': 'See Portal',
        'ad_date': None,
        'let_date': None,
        'project_type': None,
        'county': None,
        'url': cfg['portal_url'],
        'source': cfg['name'],
        'business_lines': ['highway']
    }


# =============================================================================
# DOT & RSS FETCHING
# =============================================================================

def fetch_dot_lettings() -> List[Dict]:
    lettings = []
    for state, cfg in DOT_SOURCES.items():
        print(f"  🏗️ {cfg['name']} ({state})...")
        try:
            if cfg['parser'] == 'active' and state == 'MA':
                lettings.extend(parse_massdot())
            else:
                lettings.append(create_portal_stub(state))
                print(f"    ✓ Portal link")
        except Exception as e:
            print(f"    ✗ {e}")
            lettings.append(create_portal_stub(state))
    return lettings


def fetch_rss_feeds() -> List[Dict]:
    news = []
    for source, cfg in RSS_FEEDS.items():
        try:
            print(f"  📰 {source}...")
            feed = feedparser.parse(cfg['url'], request_headers={'User-Agent': 'NECMIS/2.0'})
            count = 0
            for entry in feed.entries[:20]:
                title = entry.get('title', '')
                summary = entry.get('summary', entry.get('description', ''))
                link = entry.get('link', '')
                
                if summary:
                    summary = BeautifulSoup(summary, 'html.parser').get_text()[:300].strip()
                
                combined = f"{title} {summary}"
                if not is_construction_relevant(combined):
                    continue
                
                pub = entry.get('published_parsed') or entry.get('updated_parsed')
                date_str = datetime(*pub[:6]).strftime('%Y-%m-%d') if pub else datetime.now().strftime('%Y-%m-%d')
                
                funding_kw = ['grant', 'funding', 'award', 'federal', 'million', 'billion', '$']
                category = 'funding' if any(k in combined.lower() for k in funding_kw) else 'news'
                
                news.append({
                    'id': generate_id(link or title),
                    'title': title,
                    'summary': summary,
                    'url': link,
                    'source': source,
                    'state': cfg['state'],
                    'date': date_str,
                    'category': category,
                    'priority': get_priority(combined),
                    'business_lines': get_business_lines(combined)
                })
                count += 1
            print(f"    ✓ {count} items")
        except Exception as e:
            print(f"    ✗ {e}")
    
    news.sort(key=lambda x: x['date'], reverse=True)
    return news


# =============================================================================
# MARKET HEALTH & SUMMARY
# =============================================================================

def calculate_market_health(dot_lettings: List[Dict], news: List[Dict]) -> Dict:
    total_value = sum(d.get('cost_low') or 0 for d in dot_lettings)
    
    if total_value >= 100000000:
        dot_score, dot_trend, dot_action = 9.0, 'up', 'Expand highway capacity - strong pipeline'
    elif total_value >= 50000000:
        dot_score, dot_trend, dot_action = 8.2, 'up', 'Expand highway capacity'
    elif total_value >= 20000000:
        dot_score, dot_trend, dot_action = 7.0, 'stable', 'Maintain position'
    elif total_value > 0:
        dot_score, dot_trend, dot_action = 6.0, 'stable', 'Monitor opportunities'
    else:
        dot_score, dot_trend, dot_action = 8.2, 'up', 'Expand highway capacity'
    
    mh = {
        'dot_pipeline': {'score': dot_score, 'trend': dot_trend, 'action': dot_action},
        'housing_permits': {'score': 6.5, 'trend': 'stable', 'action': 'Monitor trends'},
        'construction_spending': {'score': 6.1, 'trend': 'down', 'action': 'Selective investment'},
        'migration': {'score': 7.3, 'trend': 'up', 'action': 'Geographic expansion'},
        'input_cost_stability': {'score': 5.5, 'trend': 'down', 'action': 'Hedge 6 months'},
        'infrastructure_funding': {'score': 7.8, 'trend': 'stable', 'action': 'Selective growth'}
    }
    
    weights = {'dot_pipeline': 0.15, 'housing_permits': 0.10, 'construction_spending': 0.10,
               'migration': 0.10, 'input_cost_stability': 0.08, 'infrastructure_funding': 0.07}
    
    total_w = sum(mh[k]['score'] * weights[k] for k in weights)
    sum_w = sum(weights.values())
    overall = round(total_w / sum_w, 1)
    
    status = 'growth' if overall >= 7.5 else 'stable' if overall >= 6.0 else 'watchlist'
    mh['overall_score'] = overall
    mh['overall_status'] = status
    
    return mh


def build_summary(dot_lettings: List[Dict], news: List[Dict]) -> Dict:
    total_low = sum(d.get('cost_low') or 0 for d in dot_lettings)
    total_high = sum(d.get('cost_high') or 0 for d in dot_lettings)
    
    by_state = {s: 0 for s in STATES}
    for d in dot_lettings:
        if d['state'] in by_state:
            by_state[d['state']] += 1
    for n in news:
        if n['state'] in by_state:
            by_state[n['state']] += 1
    
    by_cat = {
        'dot_letting': len(dot_lettings),
        'news': len([n for n in news if n['category'] == 'news']),
        'funding': len([n for n in news if n['category'] == 'funding'])
    }
    
    return {
        'total_opportunities': by_cat['dot_letting'] + by_cat['funding'],
        'total_value_low': total_low,
        'total_value_high': total_high,
        'by_state': by_state,
        'by_category': by_cat
    }


# =============================================================================
# MAIN
# =============================================================================

def run_scraper() -> Dict:
    print("=" * 60)
    print("NECMIS SCRAPER - PHASE 2 (HTML Parser)")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    print("[1/3] DOT Bid Schedules...")
    dot_lettings = fetch_dot_lettings()
    with_cost = len([d for d in dot_lettings if d.get('cost_low')])
    total_val = sum(d.get('cost_low') or 0 for d in dot_lettings)
    print(f"  Total: {len(dot_lettings)} ({with_cost} with $)")
    print(f"  Pipeline: {format_currency(total_val)}")
    print()
    
    print("[2/3] RSS Feeds...")
    news = fetch_rss_feeds()
    print(f"  Total: {len(news)} items")
    print()
    
    print("[3/3] Market Health...")
    mh = calculate_market_health(dot_lettings, news)
    print(f"  Score: {mh['overall_score']}/10 ({mh['overall_status'].upper()})")
    print(f"  DOT Pipeline: {mh['dot_pipeline']['score']}/10")
    print()
    
    summary = build_summary(dot_lettings, news)
    
    data = {
        'generated': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'),
        'summary': summary,
        'dot_lettings': dot_lettings,
        'news': news,
        'market_health': mh
    }
    
    print("=" * 60)
    print("SUMMARY")
    print("=" * 60)
    print(f"Pipeline: {format_currency(summary['total_value_low'])} - {format_currency(summary['total_value_high'])}")
    print(f"Opportunities: {summary['total_opportunities']}")
    print(f"DOT Lettings: {summary['by_category']['dot_letting']} ({with_cost} with costs)")
    print(f"News: {summary['by_category']['news']}")
    print(f"Funding: {summary['by_category']['funding']}")
    print("=" * 60)
    
    return data


if __name__ == '__main__':
    data = run_scraper()
    os.makedirs('data', exist_ok=True)
    with open('data/necmis_data.json', 'w') as f:
        json.dump(data, f, indent=2)
    print("✓ Saved to data/necmis_data.json")
