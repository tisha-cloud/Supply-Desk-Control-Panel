import os
import pandas as pd
import re

class RequirementEngine:
    def __init__(self, csv_path=None):
        if csv_path is None:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            # Primary path to extraction centralized CSV
            csv_path = os.path.join(base_dir, "..", "extraction", "centralized_database.csv")
        
        self.csv_path = os.path.abspath(csv_path)
        self.df = self._load_data()

    def _load_data(self):
        if not os.path.exists(self.csv_path):
            # Fallback to local centralized_database.csv or Excel
            excel_alt = os.path.join(os.path.dirname(self.csv_path), "BLR - Managed Office Space Supply 2026.xlsx")
            if os.path.exists(excel_alt):
                df = pd.read_excel(excel_alt, sheet_name="Master File", dtype=str).fillna("")
            else:
                raise FileNotFoundError(f"Database file not found at: {self.csv_path}")
        else:
            df = pd.read_csv(self.csv_path, dtype=str).fillna("")

        # Standardize helper columns
        area_col = 'available_inventory_sqft' if 'available_inventory_sqft' in df.columns else 'available_area_sqft'
        rent_col = 'quoted_rental_sqft_pm' if 'quoted_rental_sqft_pm' in df.columns else 'rent_rate_sqft_pm'
        
        df['area_num'] = pd.to_numeric(df[area_col].str.replace(',', '').str.extract(r'(\d+)')[0], errors='coerce').fillna(0)
        df['rent_num'] = pd.to_numeric(df[rent_col].str.replace(',', '').str.extract(r'(\d+)')[0], errors='coerce').fillna(0)
        return df

    def get_filter_options(self):
        """Returns unique filter values for UI selection."""
        dev_col = 'developer_landlord' if 'developer_landlord' in self.df.columns else 'developer_name'
        mm_col = 'micromarket_category' if 'micromarket_category' in self.df.columns else 'micromarket_location'
        fit_col = 'fitout_details' if 'fitout_details' in self.df.columns else 'fitout_status'

        developers = sorted([d for d in self.df[dev_col].unique() if d])
        micromarkets = sorted([m for m in self.df[mm_col].unique() if m])
        fitouts = sorted([f for f in self.df[fit_col].unique() if f])
        
        return {
            "developers": developers,
            "micromarkets": micromarkets,
            "fitouts": fitouts,
            "total_listings": len(self.df)
        }

    def match_requirements(self, query=None, micromarket=None, min_area=None, max_area=None, 
                           min_rent=None, max_rent=None, fitout=None, developer=None, top_n=10):
        """Matches and ranks commercial properties based on client criteria."""
        filtered = self.df.copy()

        dev_col = 'developer_landlord' if 'developer_landlord' in filtered.columns else 'developer_name'
        mm_col = 'micromarket_category' if 'micromarket_category' in filtered.columns else 'micromarket_location'
        fit_col = 'fitout_details' if 'fitout_details' in filtered.columns else 'fitout_status'
        prop_col = 'building_name' if 'building_name' in filtered.columns else 'property_name'

        # 1. Developer Filter
        if developer and developer.lower() != 'all':
            filtered = filtered[filtered[dev_col].str.lower() == developer.lower()]

        # 2. Micromarket Filter
        if micromarket and micromarket.lower() != 'all':
            filtered = filtered[filtered[mm_col].str.lower().str.contains(micromarket.lower())]

        # 3. Fitout Filter
        if fitout and fitout.lower() != 'all':
            filtered = filtered[filtered[fit_col].str.lower().str.contains(fitout.lower())]

        # 4. Area Range Filter
        if min_area is not None and float(min_area) > 0:
            filtered = filtered[filtered['area_num'] >= float(min_area)]
        if max_area is not None and float(max_area) > 0:
            filtered = filtered[(filtered['area_num'] <= float(max_area)) & (filtered['area_num'] > 0)]

        # 5. Rent Range Filter
        if min_rent is not None and float(min_rent) > 0:
            filtered = filtered[filtered['rent_num'] >= float(min_rent)]
        if max_rent is not None and float(max_rent) > 0:
            filtered = filtered[(filtered['rent_num'] <= float(max_rent)) & (filtered['rent_num'] > 0)]

        # 6. Natural Language Query Keyword Filter
        if query and query.strip():
            tokens = [t.lower() for t in re.split(r'\s+', query.strip()) if len(t) > 2]
            
            def calculate_score(row):
                score = 0
                search_text = f"{row.get(dev_col, '')} {row.get(prop_col, '')} {row.get(mm_col, '')} {row.get(fit_col, '')} {row.get('raw_remarks', '')}".lower()
                for token in tokens:
                    if token in search_text:
                        score += 1
                return score

            filtered['relevance_score'] = filtered.apply(calculate_score, axis=1)
            filtered_scored = filtered[filtered['relevance_score'] > 0].sort_values(by='relevance_score', ascending=False)
            if not filtered_scored.empty:
                filtered = filtered_scored

        # Fallback sorting: Prioritize entries with valid area & rent
        if 'relevance_score' not in filtered.columns:
            filtered = filtered.sort_values(by=['area_num', 'rent_num'], ascending=[False, True])

        records = filtered.head(top_n).to_dict(orient='records')
        return records

    def generate_summary(self, matched_records):
        """Generates executive summary analytics for selected matches."""
        if not matched_records:
            return {
                "count": 0,
                "total_area": 0,
                "avg_rent": 0,
                "micromarkets_covered": [],
                "developers_covered": []
            }

        df_matched = pd.DataFrame(matched_records)
        area_col = 'available_inventory_sqft' if 'available_inventory_sqft' in df_matched.columns else 'available_area_sqft'
        rent_col = 'quoted_rental_sqft_pm' if 'quoted_rental_sqft_pm' in df_matched.columns else 'rent_rate_sqft_pm'
        dev_col = 'developer_landlord' if 'developer_landlord' in df_matched.columns else 'developer_name'
        mm_col = 'micromarket_category' if 'micromarket_category' in df_matched.columns else 'micromarket_location'

        df_matched['area_num'] = pd.to_numeric(df_matched[area_col].astype(str).str.replace(',', '').str.extract(r'(\d+)')[0], errors='coerce').fillna(0)
        df_matched['rent_num'] = pd.to_numeric(df_matched[rent_col].astype(str).str.replace(',', '').str.extract(r'(\d+)')[0], errors='coerce').fillna(0)

        total_area = int(df_matched['area_num'].sum())
        valid_rents = df_matched[df_matched['rent_num'] > 0]['rent_num']
        avg_rent = round(float(valid_rents.mean()), 2) if not valid_rents.empty else 0

        micromarkets = [m for m in df_matched[mm_col].unique() if m]
        developers = [d for d in df_matched[dev_col].unique() if d]

        return {
            "count": len(matched_records),
            "total_area": total_area,
            "avg_rent": avg_rent,
            "micromarkets_covered": micromarkets,
            "developers_covered": developers
        }
