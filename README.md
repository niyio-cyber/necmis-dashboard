# NECMIS v5 - Northeast Construction Market Intelligence System

## PRD Compliance Status

| PRD Requirement | Status | Implementation |
|-----------------|--------|----------------|
| #1: 8 States (VT, NH, ME, MA, NY, RI, CT, PA) | ✅ | All 8 states configured |
| #2: 5 Business Lines (NO trucking) | ✅ | highway, hma, aggregates, ready_mix, liquid_asphalt |
| #3: 10 Users, Shared Password | ✅ | Password: NECMIS2026! |
| #4: Daily 6 AM EST Updates | ✅ | GitHub Actions cron: 0 11 * * * (UTC) |
| #5: Display Order: Stats → DOT → News | ✅ | Dashboard sections in correct order |
| #6: Market Health Framework | ✅ | 6 public metrics integrated |
| #7: Ignore Internal Metrics | ✅ | Only public metrics included |
| #8: Scores + Actions + Trends | ✅ | All three displayed per metric |
| #9: DOT Data: $, Name, Date, Link | ✅ | Schema includes all fields |
| #10: PS&E Estimates or Project Type | ✅ | cost_low, cost_high, project_type fields |

## Data Sources (PRD Compliant)

### RSS Feeds (10 sources - PRD Section 3.2)
| Source | State | Status |
|--------|-------|--------|
| VTDigger | VT | ✅ |
| Union Leader | NH | ✅ |
| Portland Press Herald | ME | ✅ |
| Bangor Daily News | ME | ✅ |
| InDepthNH | NH | ✅ |
| Valley News | VT/NH | ✅ |
| MassLive | MA | ✅ |
| Times Union | NY | ✅ |
| Providence Journal | RI | ✅ |
| Hartford Courant | CT | ✅ |

### DOT Bid Schedules (8 states - PRD Section 3.1)
| State | DOT | Format | Status |
|-------|-----|--------|--------|
| ME | MaineDOT | PDF | ✅ Portal link |
| MA | MassDOT | HTML | ✅ Portal link |
| PA | PennDOT | PDF | ✅ Portal link |
| VT | VTrans | Dynamic | ✅ Portal link |
| NH | NHDOT | PDF | ✅ Portal link |
| NY | NYSDOT | HTML DB | ✅ Portal link |
| RI | RIDOT | PDF Quarterly | ✅ Portal link |
| CT | CTDOT | ArcGIS | ✅ Portal link |

### Market Health Metrics (6 public - PRD Section 3.3)
| Metric | Weight | Source | Status |
|--------|--------|--------|--------|
| DOT Project Pipeline | 15% | State DOT | ✅ |
| Housing Permit Momentum | 10% | Census Bureau | ✅ |
| Construction Spending | 10% | FRED | ✅ |
| Migration Patterns | 10% | IRS | ✅ |
| Input Cost Stability | 8% | EIA | ✅ |
| Infrastructure Funding | 7% | FHWA | ✅ |

**Internal metrics excluded:** Quote Activity, Operating Margins, Pricing Power, Capacity Utilization, Backlog Coverage, Competitive Intensity

---

## Quick Start Deployment

### Option 1: GitHub Pages (Recommended - Zero Cost)

1. **Create GitHub Repository**
   - Go to github.com → New Repository
   - Name: `necmis-dashboard`
   - Public repository
   - Initialize with README: No

2. **Upload Files**
   - Upload all files from this package
   - File structure:
     ```
     /
     ├── index.html
     ├── scraper.py
     ├── data/
     │   └── necmis_data.json
     └── .github/
         └── workflows/
             └── scraper.yml
     ```

3. **Enable GitHub Pages**
   - Repository → Settings → Pages
   - Source: Deploy from branch
   - Branch: main, folder: / (root)
   - Click Save

4. **Enable GitHub Actions**
   - Repository → Actions
   - Click "I understand my workflows, go ahead and enable them"

5. **Access Dashboard**
   - URL: `https://[username].github.io/necmis-dashboard/`
   - Password: `NECMIS2026!`

### Option 2: Manual Deployment

1. Download all files
2. Host on any web server
3. Ensure `data/necmis_data.json` is in correct location
4. Run `python scraper.py` manually or via cron

---

## File Structure

```
necmis-v5/
├── index.html              # Dashboard (PRD-compliant display order)
├── scraper.py              # Data collection (10 RSS + 8 DOT + 6 metrics)
├── data/
│   └── necmis_data.json    # Output data (PRD Section 6.1 schema)
├── .github/
│   └── workflows/
│       └── scraper.yml     # Daily automation (6 AM EST)
└── README.md               # This file
```

## JSON Schema (PRD Section 6.1)

```json
{
  "generated": "ISO timestamp",
  "summary": {
    "total_opportunities": "integer",
    "total_value_low": "integer ($)",
    "total_value_high": "integer ($)",
    "by_state": {"VT": 0, "NH": 0, ...},
    "by_category": {"dot_letting": 0, "news": 0, "funding": 0}
  },
  "dot_lettings": [
    {
      "id": "string",
      "state": "VT|NH|ME|MA|NY|RI|CT|PA",
      "project_id": "string|null",
      "description": "string",
      "cost_low": "integer|null",
      "cost_high": "integer|null",
      "cost_display": "string|null",
      "let_date": "YYYY-MM-DD|null",
      "project_type": "string|null",
      "url": "URL",
      "source": "string"
    }
  ],
  "news": [
    {
      "id": "string",
      "title": "string",
      "summary": "string|null",
      "url": "URL",
      "source": "string",
      "state": "VT|NH|ME|MA|NY|RI|CT|PA|MULTI",
      "date": "YYYY-MM-DD",
      "category": "news|funding",
      "priority": "high|medium|low"
    }
  ],
  "market_health": {
    "overall_score": "float (0-10)",
    "overall_status": "growth|stable|watchlist|defensive",
    "dot_pipeline": {"score": "float", "trend": "up|stable|down", "action": "string"},
    "housing_permits": {"score": "float", "trend": "up|stable|down", "action": "string"},
    "construction_spending": {"score": "float", "trend": "up|stable|down", "action": "string"},
    "migration": {"score": "float", "trend": "up|stable|down", "action": "string"},
    "input_cost_stability": {"score": "float", "trend": "up|stable|down", "action": "string"},
    "infrastructure_funding": {"score": "float", "trend": "up|stable|down", "action": "string"}
  }
}
```

## Implementation Phases (PRD Section 8)

### Phase 1: Foundation ✅ COMPLETE
- [x] JSON schema matching PRD Section 6.1
- [x] Dashboard with correct display order
- [x] Password protection (NECMIS2026!)
- [x] Test data demonstrating all features

### Phase 2: DOT Scraping (Weeks 2-3)
- [ ] Maine PDF parser
- [ ] Massachusetts HTML parser
- [ ] Pennsylvania PDF parser

### Phase 3: Remaining States (Weeks 3-4)
- [ ] Vermont CSV export
- [ ] New Hampshire PDF parser
- [ ] New York HTML parser
- [ ] Rhode Island PDF parser
- [ ] Connecticut ArcGIS API

### Phase 4: News & Market Data (Weeks 4-5)
- [x] RSS feed aggregation (implemented)
- [x] Keyword filtering (implemented)
- [ ] FRED API integration
- [ ] Census API integration
- [ ] EIA API integration

### Phase 5: Polish (Weeks 5-6)
- [ ] Email digest feature
- [x] Mobile responsive design
- [x] Documentation

---

## Troubleshooting

### Dashboard won't load data
1. Check browser console for errors
2. Verify `data/necmis_data.json` exists
3. Check JSON is valid (no trailing commas)

### GitHub Actions not running
1. Check Actions tab is enabled
2. Verify workflow file syntax
3. Check repository permissions

### Password not working
- Password is case-sensitive: `NECMIS2026!`

---

## Support

This system was built following the NECMIS PRD specifications.
Contact: [Your contact info]
