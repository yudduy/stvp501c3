
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Updated Streamlit App for Real-time Balance Check
Integrated with Additional Indicators from balance_group_check.py
"""

import streamlit as st
import pandas as pd
import numpy as np
import altair as alt
import requests
import json
import itertools
from scipy.stats import ttest_ind
from itertools import combinations

# Function to fetch and process data from URL
def fetch_and_process_data(url):
    response = requests.get(url)
    if response.status_code != 200:
        raise Exception(f"Failed to fetch data from {url}. HTTP Status Code: {response.status_code}")

    raw_data = [json.loads(line) for line in response.text.splitlines() if line.strip()]
    clean_tracker = pd.json_normalize(raw_data)[['timestamp', 'uuid', 'event', 'data.group', 'data.url', 'data.sessionCount', 'data.referrer']]
    clean_tracker.columns = ['timestamp', 'uuid', 'event', 'group', 'url', 'sessionCount', 'referrer']
    clean_tracker['timestamp'] = pd.to_datetime(clean_tracker['timestamp'], errors='coerce', utc=True)
    return clean_tracker

# Function to process the tracker data
def process_clean_tracker(clean_tracker):
    clean_tracker['test_group'] = clean_tracker['event'].str.extract(r'(test_group_v\d+)').ffill()
    clean_tracker['test_group'].fillna('test_group_v1', inplace=True)
    clean_tracker['random_group'] = clean_tracker.groupby(['uuid', 'test_group'])['group'].transform(lambda g: g.ffill().bfill())
    return clean_tracker

# Function to calculate additional metrics
def process_event_data(clean_tracker):
    def count_event(event_series, event_name):
        return (event_series == event_name).sum()

    def calculate_homepage_pct(url_series, event_series):
        page_view_count = (event_series == 'page_view').sum()
        if page_view_count > 0:
            return (url_series == 'https://checkmyads.org/').sum() / page_view_count
        return np.nan

    def check_url_presence(url_series, keyword):
        return int(any(isinstance(ref, str) and keyword in ref.lower() for ref in url_series))

    uuid_tracker = clean_tracker.groupby('uuid').agg(
        random_group=('random_group', 'first'),
        num_sessions=('event', lambda x: count_event(x, 'session_start')),
        num_page_views=('event', lambda x: count_event(x, 'page_view')),
        num_referral=('event', lambda x: count_event(x, 'referral')),
        num_newsletter_signup=('event', lambda x: count_event(x, 'newsletter_signup')),
        num_donation=('event', lambda x: count_event(x, 'donation')),

        first_session_start_time=('timestamp', lambda x: x.loc[clean_tracker['event'] == 'session_start'].min()),
        average_session_start_time=('timestamp', lambda x: x.loc[clean_tracker['event'] == 'session_start'].mean()),
        last_session_start_time=('timestamp', lambda x: x.loc[clean_tracker['event'] == 'session_start'].max()),

        homepage_pct=('url', lambda x: calculate_homepage_pct(x, clean_tracker['event'])),

        view_about=('url', lambda x: check_url_presence(x, 'checkmyads.org/about')),
        view_news=('url', lambda x: check_url_presence(x, 'checkmyads.org/news')),
        view_donate=('url', lambda x: check_url_presence(x, 'checkmyads.org/donate')),
        view_google_trial=('url', lambda x: check_url_presence(x, 'checkmyads.org/google')),
        view_shop=('url', lambda x: check_url_presence(x, 'checkmyads.org/shop')),

        referral_google=('referrer', lambda x: check_url_presence(x, 'google')),
        referral_pcgamer=('referrer', lambda x: check_url_presence(x, 'pcgamer')),
        referral_globalprivacycontrol=('referrer', lambda x: check_url_presence(x, 'globalprivacycontrol')),
        referral_duckduckgo=('referrer', lambda x: check_url_presence(x, 'duckduckgo'))
    ).reset_index()

    return uuid_tracker

# Function to calculate statistics
def calculate_statistics(uuid_tracker):
    group_stats = uuid_tracker.groupby('random_group').agg(
        num_uuid=('uuid', 'nunique'),
        num_sessions_mean=('num_sessions', 'mean'),
        num_page_views_mean=('num_page_views', 'mean'),
        num_referral_mean=('num_referral', 'mean'),
        num_newsletter_signup_mean=('num_newsletter_signup', 'mean'),
        num_donation_mean=('num_donation', 'mean'),
        homepage_pct_mean=('homepage_pct', 'mean'),
        view_about_mean=('view_about', 'mean'),
        view_news_mean=('view_news', 'mean'),
        view_donate_mean=('view_donate', 'mean'),
        view_google_trial_mean=('view_google_trial', 'mean'),
        view_shop_mean=('view_shop', 'mean'),
        referral_google_mean=('referral_google', 'mean'),
        referral_pcgamer_mean=('referral_pcgamer', 'mean'),
        referral_globalprivacycontrol_mean=('referral_globalprivacycontrol', 'mean'),
        referral_duckduckgo_mean=('referral_duckduckgo', 'mean')
    ).reset_index()
    return group_stats

# Function to calculate p-values
def calculate_p_values(uuid_tracker):
    p_values = []
    random_groups = uuid_tracker['random_group'].unique()

    for g1, g2 in combinations(random_groups, 2):
        for metric in uuid_tracker.columns.difference(['uuid', 'random_group']):
            g1_data = uuid_tracker[uuid_tracker['random_group'] == g1][metric].dropna()
            g2_data = uuid_tracker[uuid_tracker['random_group'] == g2][metric].dropna()

            if len(g1_data) > 1 and len(g2_data) > 1:
                _, p_val = ttest_ind(g1_data, g2_data, equal_var=False)
                p_values.append({'metric': metric, 'group_pair': f"{g1} vs {g2}", 'p_value': p_val})

    return pd.DataFrame(p_values)


def datetime_to_numeric(df, datetime_cols):
    for col in datetime_cols:
        # Convert column to datetime first
        df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # Check if already timezone-aware
        if df[col].dt.tz is None:  # tz-naive
            df[col] = df[col].dt.tz_localize('UTC')
        else:  # tz-aware
            df[col] = df[col].dt.tz_convert(None)
        
        # Convert to seconds since epoch
        df[col] = (df[col] - pd.Timestamp("1970-01-01")) // pd.Timedelta('1s')
    return df


def convert_datetime_back(group_stats, datetime_cols):
    for col in datetime_cols:
        # Convert mean back to readable datetime format
        group_stats[(col, 'mean')] = pd.to_datetime(group_stats[(col, 'mean')], unit='s')
        
        # Convert SD back to days (since it was in seconds originally)
        group_stats[(col, 'std')] = group_stats[(col, 'std')] / (60 * 60 * 24)  # Convert seconds to days
    return group_stats


def gen_output_tables(df, datetime_cols):
    # Convert datetime columns to numeric for calculations (seconds precision only)
    df = datetime_to_numeric(df, datetime_cols)
    print(df.columns)
    print(df['random_group'])

    # Select numeric columns only
    numeric_cols = df.select_dtypes(include=['float64', 'int64']).columns.tolist()
    print(numeric_cols)
    print(df.columns)
    numeric_cols.remove('random_group')  # Exclude the grouping variable
    numeric_df = df[['random_group'] + numeric_cols]
    print(df.columns)

    # Calculate mean and standard deviation by random group
    group_stats = numeric_df.groupby('random_group').agg(['mean', 'std'])
    group_stats = convert_datetime_back(group_stats, datetime_cols)   # Apply the conversion back

    # Prepare for pairwise comparisons
    groups = sorted(numeric_df['random_group'].unique())
    pairwise_results = []

    # Perform pairwise t-tests
    for (group1, group2) in itertools.combinations(groups, 2):
        group1_data = numeric_df[numeric_df['random_group'] == group1]
        group2_data = numeric_df[numeric_df['random_group'] == group2]
        
        for col in numeric_cols:
            stat, p_value = ttest_ind(group1_data[col].dropna(), group2_data[col].dropna(), equal_var=False)
            pairwise_results.append({'Characteristic': col, 
                                     'Group 1': group1, 
                                     'Group 2': group2, 
                                     'p-value': p_value})

    # Convert results to a dataframe
    pairwise_results_df = pd.DataFrame(pairwise_results)
    
    # Output LaTeX table
    for col in numeric_cols:
        # Extract summary statistics for the current characteristic
        summary_stats_col = group_stats[col].reset_index()
        summary_stats_col.columns = ['random_group', 'Mean', 'SD']
        
        # Extract pairwise p-values for the current characteristic
        pairwise_p_values_col = pairwise_results_df[pairwise_results_df['Characteristic'] == col]
        pairwise_p_values_col = pairwise_p_values_col.drop(columns=['Characteristic'])

        
        # Save LaTeX files
        # summary_stats_col.to_latex(f"{output_path}summary_{col}.tex", index=False)
        # pairwise_p_values_col.to_latex(f"{output_path}pairwise_p_{col}.tex", index=False)
        caption_input = col.replace("_", " ")
        # Display summary statistics
        st.subheader(f"Statistics for {caption_input}")
        if not summary_stats_col.empty:
            st.write(summary_stats_col)
        else:
            st.write("No data available for the {caption_input}.")
        st.subheader(f"P-value comparison for {caption_input}")
        if not pairwise_p_values_col.empty:
            st.write(pairwise_p_values_col)
        else:
            st.write("No data available for the {caption_input}.")

    return group_stats, pairwise_results_df

# %%
# URL for fetching data
url = 'https://checkmyads.org/wp-content/themes/checkmyads/tracker-data.txt'
clean_tracker = fetch_and_process_data(url)
clean_tracker = process_clean_tracker(clean_tracker)
clean_tracker = clean_tracker[~clean_tracker['random_group'].isna()]

# Dropdown for selecting test group
available_test_groups = clean_tracker['test_group'].unique()
available_test_groups = available_test_groups[::-1]

# Streamlit application setup
st.set_page_config(page_title="Enhanced Balance Check", page_icon="📊", layout="wide")
st.title("📊 Real-time Balance Check")
st.subheader("Select Test Group")
selected_test_group = st.selectbox("Test Group:", options=available_test_groups)
selected_clean_tracker = clean_tracker[clean_tracker['test_group'] == selected_test_group]
selected_uuid_tracker = process_event_data(selected_clean_tracker)

# %%
group_stats, pairwise_results = gen_output_tables(
    selected_uuid_tracker, 
    datetime_cols = ['first_session_start_time', 'average_session_start_time', 'last_session_start_time'])


summary_stats = calculate_statistics(selected_uuid_tracker)
filtered_data = summary_stats[summary_stats['random_group'] == selected_test_group]

# Generate a bar chart
if not filtered_data.empty:
    bar_chart = (
        alt.Chart(filtered_data)
        .mark_bar()
        .encode(
            x=alt.X('random_group:N', title='Group'),
            y=alt.Y('num_uuid:Q', title='Number of UUIDs'),
            tooltip=[col for col in filtered_data.columns if col != 'random_group']
        )
        .properties(title=f"Group Statistics ({selected_test_group})", height=400)
    )
    st.altair_chart(bar_chart, use_container_width=True)
else:
    st.write("No data available for visualization.")

# %%
