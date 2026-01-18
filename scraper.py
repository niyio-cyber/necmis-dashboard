#!/usr/bin/env python3
"""
NECMIS Scraper - Phase 2.2 (MA + ME Parsers)
=============================================
- MA: HTML text extraction with project details
- ME: Excel parsing from weekly schedule (NEW)

Data Sources:
- MA: hwy.massdot.state.ma.us/webapps/const/statusReport.asp (HTML)
- ME: maine.gov/dot/.../monthly.xls (Excel with cost estimates)
"""

import json
import hashlib
import re
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
import tempfile

try:
    import requests
    import feedparser
    from bs4 import BeautifulSoup
except ImportError as e:
    print(f"Missing dependency: {e}")
    raise

# Try to import pandas for ME Excel parsing
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("⚠️ pandas not available - ME Excel parser disabled")


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
    'MA': {
        'name': 'MassDOT', 
        'portal_url': 'https://hwy.massdot.state.ma.us/webapps/const/statusReport.asp', 
        'parser': 'active'
    },
    'ME': {
        'name': 'MaineDOT', 
        'portal_url': 'https://www.maine.gov/dot/major-projects/cap/schedule',
        'excel_url': 'https://www.maine.gov/dot/sites/maine.gov.dot/files/inline-files/monthly.xls',
        'parser': 'active'  # NOW ACTIVE
    },
    'NH': {
        'name': 'NHDOT', 
        'portal_url': 'https://www.dot.nh.gov/doing-business-nhdot/contractors/invitation-bid', 
        'parser': 'stub'
    },
    'VT': {
        'name': 'VTrans', 
        'portal_url': 'https://vtrans.vermont.gov/contract-admin/bids-requests/construction-contracting', 
        'parser': 'stub'
    },
    'NY': {
        'name': 'NYSDOT', 
        'portal_url': 'https://www.dot.ny.gov/doing-business/opportunities/const-highway', 
        'parser': 'stub'
    },
    'RI': {
        'name': 'RIDOT', 
        'portal_url': 'https://www.dot.ri.gov/about/current_projects.php', 
        'parser': 'stub'
    },
    'CT': {
        'name': 'CTDOT', 
        'portal_url': 'https://portal.ct.gov/DOT/Doing-Business/Contractor-Information', 
        'parser': 'stub'
    },
    'PA': {
        'name': 'PennDOT', 
        'portal_url': 'https://www.penndot.pa.gov/business/Letting/Pages/default.aspx', 
        'parser': 'stub'
    }
}

CONSTRUCTION_KEYWORDS = {
    'high_priority': ['highway', 'bridge', 'DOT', 'bid', 'letting', 'RFP', 'contract award', 'paving', 'resurfacing', 'infrastructure', 'IIJA', 'federal grant'],
    'medium_priority': ['construction', 'road', 'pavement', 'asphalt', 'concrete', 'aggregate', 'gravel', 'development', 'permit', 'municipal'],
    'business_line_keywords': {
        'highway': ['highway', 'road', 'interstate', 'route', 'bridge', 'DOT', 'transportation', 'reconstruction', 'resurfacing'],
        'hma': ['asphalt', 'paving', 'resurfacing', 'overlay', 'milling', 'HMA', 'hot mix', 'surfacing', 'pavement'],
        'aggregates': ['aggregate', 'gravel', 'sand', 'stone', 'quarry'],
        'ready_mix': ['concrete', 'ready-mix', 'cement', 'bridge deck', 'deck'],
        'liquid_asphalt': ['liquid asphalt', 'bitumen', 'emulsion']
    }
}

# ME work type to business line mapping
ME_WORK_TYPE_MAPPING = {
    'Highway Construction': ['highway', 'hma', 'aggregates'],
    'Highway Preservation Paving': ['highway', 'hma'],
    'Highway Light Capital Paving (LCP)': ['highway', 'hma'],
    'Highway Safety and Spot Improvements': ['highway'],
    'Bridge Construction': ['highway', 'aggregates', 'ready_mix'],
    'Bridge Other': ['highway'],
    'Multimodal': ['highway']
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
    if isinstance(text, (int, float)):
        return float(text)
    cleaned = re.sub(r'[,$]', '', str(text).strip())
    try:
        return float(cleaned)
    except ValueError:
        return None

def clean_location(loc: str) -> str:
    if not loc:
        return None
    loc = str(loc).strip()
    if loc.upper().startswith('DISTRICT'):
        num = re.search(r'\d+', loc)
        return f"District {num.group()}" if num else "Various Locations"
    return loc.title()


# =============================================================================
# MASSDOT PARSER (HTML/Plain Text)
# =============================================================================

def parse_massdot() -> List[Dict]:
    """Parse MassDOT by converting HTML to plain text first."""
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
        
        soup = BeautifulSoup(html, 'html.parser')
        for script in soup(["script", "style"]):
            script.decompose()
        
        text = soup.get_text(separator='\n')
        text = re.sub(r'\n\s*\n', '\n', text)
        
        print(f"    📝 Converted to {len(text)} chars of text")
        
        # Split into project blocks
        blocks = re.split(r'(?=Location:)', text)
        print(f"    📦 Found {len(blocks)} potential project blocks")
        
        projects = []
        for block in blocks:
            if 'Project Value:' not in block:
                continue
            
            loc_match = re.search(r'Location:\s*([A-Z][A-Za-z0-9\s\-,]+?)(?:\s+Description:|$)', block)
            desc_match = re.search(r'Description:\s*(.+?)(?:\s+District:|$)', block, re.DOTALL)
            value_match = re.search(r'Project Value:\s*\$([0-9,]+\.?\d*)', block)
            proj_num_match = re.search(r'Project Number:\s*(\d+)', block)
            proj_type_match = re.search(r'Project Type:\s*([^\n]+)', block)
            ad_date_match = re.search(r'Ad Date:\s*(\d{1,2}/\d{1,2}/\d{4})', block)
            district_match = re.search(r'District:\s*(\d+)', block)
            
            if value_match:
                projects.append({
                    'location': loc_match.group(1).strip() if loc_match else None,
                    'description': desc_match.group(1).strip()[:200] if desc_match else None,
                    'value': value_match.group(1),
                    'project_num': proj_num_match.group(1) if proj_num_match else None,
                    'project_type': proj_type_match.group(1).strip() if proj_type_match else None,
                    'ad_date': ad_date_match.group(1) if ad_date_match else None,
                    'district': district_match.group(1) if district_match else None
                })
        
        print(f"    📊 Extracted {len(projects)} projects with values")
        
        # Fallback: line-by-line extraction
        if not projects:
            print(f"    🔄 Trying line-by-line extraction...")
            values = re.findall(r'Project Value:\s*\$([0-9,]+\.?\d*)', text)
            locations = re.findall(r'Location:\s*([A-Z][A-Za-z0-9\s\-,]+)', text)
            descriptions = re.findall(r'Description:\s*(.+?)(?=\s*District:|\n)', text)
            proj_nums = re.findall(r'Project Number:\s*(\d+)', text)
            proj_types = re.findall(r'Project Type:\s*([^\n]+)', text)
            ad_dates = re.findall(r'Ad Date:\s*(\d{1,2}/\d{1,2}/\d{4})', text)
            districts = re.findall(r'District:\s*(\d+)\s*Ad Date:', text)
            
            print(f"    Line extraction: {len(values)} val, {len(locations)} loc, {len(descriptions)} desc")
            
            for i in range(len(values)):
                projects.append({
                    'location': locations[i] if i < len(locations) else None,
                    'description': descriptions[i][:200] if i < len(descriptions) else None,
                    'value': values[i],
                    'project_num': proj_nums[i] if i < len(proj_nums) else None,
                    'project_type': proj_types[i].strip() if i < len(proj_types) else None,
                    'ad_date': ad_dates[i] if i < len(ad_dates) else None,
                    'district': districts[i] if i < len(districts) else None
                })
        
        # Fallback: dollar-only extraction
        if not projects:
            print(f"    🔄 Falling back to dollar-only extraction...")
            all_values = re.findall(r'\$([0-9,]+\.?\d*)', text)
            for i, v in enumerate(all_values):
                val = parse_currency(v)
                if val and 100000 <= val <= 500000000:
                    projects.append({
                        'location': None,
                        'description': f"MassDOT Project #{i+1}",
                        'value': v,
                        'project_num': None,
                        'project_type': None,
                        'ad_date': None,
                        'district': None
                    })
        
        # Build letting records
        for p in projects[:50]:
            cost = parse_currency(p['value'])
            if not cost:
                continue
            
            location = clean_location(p['location'])
            desc = p['description'] or f"MassDOT Project - {location or 'Various Locations'}"
            desc = re.sub(r'\s+', ' ', desc).strip()
            
            proj_type = p['project_type']
            if proj_type:
                proj_type = re.sub(r'\s*,\s*$', '', proj_type)[:60]
            
            ad_date = None
            if p['ad_date']:
                try:
                    ad_date = datetime.strptime(p['ad_date'], '%m/%d/%Y').strftime('%Y-%m-%d')
                except:
                    pass
            
            district = int(p['district']) if p['district'] else None
            
            project_url = url
            if p['project_num']:
                project_url = f"{url}?projnum={p['project_num']}"
            
            letting = {
                'id': generate_id(f"MA-{p['project_num'] or cost}-{desc[:25]}"),
                'state': 'MA',
                'project_id': p['project_num'],
                'description': desc[:200],
                'cost_low': int(cost),
                'cost_high': int(cost),
                'cost_display': format_currency(cost),
                'ad_date': ad_date,
                'let_date': None,
                'project_type': proj_type,
                'location': location,
                'district': district,
                'url': project_url,
                'source': 'MassDOT',
                'business_lines': get_business_lines(f"{desc} {proj_type or ''}")
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


# =============================================================================
# MAINEDOT PARSER (Excel) - NEW
# =============================================================================

def parse_mainedot() -> List[Dict]:
    """
    Parse MaineDOT weekly Construction Advertisement Schedule Excel file.
    Source: maine.gov/dot/sites/maine.gov.dot/files/inline-files/monthly.xls
    
    Excel Columns:
    - Work Type
    - Advertise Date
    - Scope
    - Location/Title
    - Details
    - Project Identification No.
    - Administered By
    - Total Project Estimate
    """
    if not PANDAS_AVAILABLE:
        print(f"    ⚠️ pandas not available, using portal stub")
        return [create_portal_stub('ME')]
    
    cfg = DOT_SOURCES['ME']
    lettings = []
    
    try:
        print(f"    🔍 Fetching MaineDOT Excel...")
        
        # Download Excel file
        response = requests.get(cfg['excel_url'], timeout=30, headers={
            'User-Agent': 'Mozilla/5.0 (compatible; NECMIS/2.0)'
        })
        response.raise_for_status()
        
        # Save to temp file
        with tempfile.NamedTemporaryFile(suffix='.xls', delete=False) as f:
            f.write(response.content)
            temp_path = f.name
        
        print(f"    📄 Downloaded {len(response.content):,} bytes")
        
        # Read Excel
        try:
            df = pd.read_excel(temp_path, engine='xlrd')
        except Exception:
            df = pd.read_excel(temp_path, engine='openpyxl')
        
        print(f"    📊 Loaded {len(df)} rows")
        print(f"    Columns: {list(df.columns)[:5]}...")
        
        # Normalize column names
        df.columns = [str(c).strip() for c in df.columns]
        
        # Map columns (handle variations in column names)
        col_map = {}
        for col in df.columns:
            col_lower = col.lower()
            if 'work type' in col_lower:
                col_map['work_type'] = col
            elif 'advertise' in col_lower and 'date' in col_lower:
                col_map['ad_date'] = col
            elif 'scope' in col_lower:
                col_map['scope'] = col
            elif 'location' in col_lower or 'title' in col_lower:
                col_map['location'] = col
            elif 'detail' in col_lower:
                col_map['details'] = col
            elif 'project' in col_lower and ('id' in col_lower or 'no' in col_lower or 'identification' in col_lower):
                col_map['project_id'] = col
            elif 'administered' in col_lower:
                col_map['admin'] = col
            elif 'estimate' in col_lower or 'total' in col_lower:
                col_map['cost'] = col
        
        # Parse each row
        for idx, row in df.iterrows():
            try:
                work_type = str(row.get(col_map.get('work_type', ''), '')).strip()
                location = str(row.get(col_map.get('location', ''), '')).strip()
                project_id = str(row.get(col_map.get('project_id', ''), '')).strip()
                
                # Skip empty rows
                if not location or location.lower() == 'nan' or not location:
                    continue
                
                # Parse cost
                cost_raw = row.get(col_map.get('cost', ''))
                cost = None
                if pd.notna(cost_raw):
                    cost_str = str(cost_raw).replace('$', '').replace(',', '').strip()
                    try:
                        cost = float(cost_str)
                    except ValueError:
                        pass
                
                # Parse date
                ad_date_raw = row.get(col_map.get('ad_date', ''))
                ad_date = None
                if pd.notna(ad_date_raw):
                    if isinstance(ad_date_raw, datetime):
                        ad_date = ad_date_raw.strftime('%Y-%m-%d')
                    else:
                        try:
                            ad_date = pd.to_datetime(ad_date_raw).strftime('%Y-%m-%d')
                        except:
                            pass
                
                # Build description
                scope = str(row.get(col_map.get('scope', ''), '')).strip()
                details = str(row.get(col_map.get('details', ''), '')).strip()
                
                description = location
                if scope and scope.lower() != 'nan':
                    description = f"{scope}: {location}"
                if details and details.lower() != 'nan':
                    description += f" - {details}"
                
                # Get business lines from work type
                business_lines = []
                for wt, bl in ME_WORK_TYPE_MAPPING.items():
                    if wt.lower() in work_type.lower():
                        business_lines.extend(bl)
                if not business_lines:
                    business_lines = get_business_lines(description)
                business_lines = list(set(business_lines))
                
                # Clean project_id
                if project_id.lower() == 'nan':
                    project_id = None
                
                # Determine priority
                priority = 'high' if cost and cost >= 1000000 else 'medium' if cost and cost >= 100000 else 'low'
                
                letting = {
                    'id': generate_id(f"ME-{project_id or idx}-{location[:25]}"),
                    'state': 'ME',
                    'project_id': project_id,
                    'description': description[:250],
                    'cost_low': int(cost) if cost else None,
                    'cost_high': int(cost) if cost else None,
                    'cost_display': format_currency(cost) if cost else 'See Portal',
                    'ad_date': ad_date,
                    'let_date': None,
                    'project_type': work_type if work_type.lower() != 'nan' else None,
                    'location': location,
                    'district': None,
                    'url': cfg['portal_url'],
                    'source': 'MaineDOT',
                    'business_lines': business_lines
                }
                lettings.append(letting)
                
            except Exception as e:
                print(f"    ⚠️ Row {idx} error: {e}")
                continue
        
        # Cleanup temp file
        try:
            os.remove(temp_path)
        except:
            pass
        
        if lettings:
            with_cost = len([l for l in lettings if l.get('cost_low')])
            total = sum(l.get('cost_low') or 0 for l in lettings)
            print(f"    ✓ {len(lettings)} projects ({with_cost} with $), {format_currency(total)} total pipeline")
        else:
            print(f"    ⚠ No projects parsed from Excel")
            lettings.append(create_portal_stub('ME'))
            
    except Exception as e:
        print(f"    ✗ Error: {e}")
        import traceback
        traceback.print_exc()
        lettings.append(create_portal_stub('ME'))
    
    return lettings


# =============================================================================
# PORTAL STUB & FETCHING
# =============================================================================

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
        'location': None,
        'district': None,
        'url': cfg['portal_url'],
        'source': cfg['name'],
        'business_lines': ['highway']
    }


def fetch_dot_lettings() -> List[Dict]:
    lettings = []
    for state, cfg in DOT_SOURCES.items():
        print(f"  🏗️ {cfg['name']} ({state})...")
        try:
            if cfg['parser'] == 'active':
                if state == 'MA':
                    lettings.extend(parse_massdot())
                elif state == 'ME':
                    lettings.extend(parse_mainedot())
                else:
                    lettings.append(create_portal_stub(state))
                    print(f"    ✓ Portal link")
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
    print("NECMIS SCRAPER - PHASE 2.2 (MA + ME Parsers)")
    print("=" * 60)
    print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Pandas available: {PANDAS_AVAILABLE}")
    print()
    
    print("[1/3] DOT Bid Schedules...")
    dot_lettings = fetch_dot_lettings()
    with_cost = len([d for d in dot_lettings if d.get('cost_low')])
    with_details = len([d for d in dot_lettings if d.get('project_type') or d.get('location')])
    total_val = sum(d.get('cost_low') or 0 for d in dot_lettings)
    print(f"  Total: {len(dot_lettings)} ({with_cost} with $, {with_details} with details)")
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
    print(f"Pipeline: {format_currency(summary['total_value_low'])}")
    print(f"Opportunities: {summary['total_opportunities']}")
    print(f"DOT Lettings: {summary['by_category']['dot_letting']} ({with_cost} with costs, {with_details} with details)")
    print(f"News: {summary['by_category']['news']}")
    print(f"Funding: {summary['by_category']['funding']}")
    print()
    print("By State:")
    for state in ['MA', 'ME', 'VT', 'NH']:
        count = len([d for d in dot_lettings if d['state'] == state])
        val = sum(d.get('cost_low') or 0 for d in dot_lettings if d['state'] == state)
        print(f"  {state}: {count} projects, {format_currency(val)}")
    print("=" * 60)
    
    return data


if __name__ == '__main__':
    data = run_scraper()
    os.makedirs('data', exist_ok=True)
    with open('data/necmis_data.json', 'w') as f:
        json.dump(data, f, indent=2)
    print("✓ Saved to data/necmis_data.json")
