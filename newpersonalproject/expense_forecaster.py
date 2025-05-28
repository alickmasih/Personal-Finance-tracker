from typing import Dict, List, Tuple, Optional
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import StandardScaler
from sqlalchemy import func
from models import Transaction

class ExpenseForecaster:
    def __init__(self):
        self.model = LinearRegression()
        self.scaler = StandardScaler()
        self.is_trained = False

    def prepare_features(self, transactions: List[Transaction]) -> Tuple[pd.DataFrame, pd.Series]:
        """
        Prepare features from transaction history.
        
        Args:
            transactions: List of Transaction objects
            
        Returns:
            X: Feature DataFrame
            y: Target Series (monthly expenses)
        """
        # Convert transactions to DataFrame
        df = pd.DataFrame([{
            'amount': t.amount,
            'type': t.type,
            'category': t.category,
            'date': t.date,
        } for t in transactions])
        
        if df.empty:
            return pd.DataFrame(), pd.Series()
        
        # Keep only expenses
        df = df[df['type'] == 'expense']
        
        # Group by month and calculate features
        monthly_data = []
        unique_months = sorted(df['date'].dt.to_period('M').unique())
        
        for month in unique_months:
            month_df = df[df['date'].dt.to_period('M') == month]
            
            # Calculate features for this month
            features = {
                'month_num': month.month,  # Capture seasonality
                'total_transactions': len(month_df),
                'avg_transaction': month_df['amount'].mean(),
                'max_transaction': month_df['amount'].max(),
                'min_transaction': month_df['amount'].min(),
            }
            
            # Add category-wise spending
            for category in df['category'].unique():
                cat_total = month_df[month_df['category'] == category]['amount'].sum()
                features[f'cat_{category.lower().replace(" & ", "_")}'] = cat_total
            
            # Add target (total expenses for the month)
            features['total_expenses'] = month_df['amount'].sum()
            
            monthly_data.append(features)
        
        # Convert to DataFrame
        monthly_df = pd.DataFrame(monthly_data)
        
        # Separate features and target
        target = monthly_df['total_expenses']
        features = monthly_df.drop('total_expenses', axis=1)
        
        return features, target

    def train(self, transactions: List[Transaction]) -> bool:
        """
        Train the forecasting model on historical transaction data.
        
        Args:
            transactions: List of Transaction objects
            
        Returns:
            bool: True if training was successful
        """
        X, y = self.prepare_features(transactions)
        
        if len(X) < 2:  # Need at least 2 months of data
            return False
        
        # Scale features
        X_scaled = self.scaler.fit_transform(X)
        
        # Train model
        self.model.fit(X_scaled, y)
        self.is_trained = True
        
        return True

    def predict_next_month(self, transactions: List[Transaction]) -> Dict[str, float]:
        """
        Predict expenses for next month.
        
        Args:
            transactions: List of Transaction objects
            
        Returns:
            Dict containing prediction and confidence score
        """
        if not self.is_trained:
            if not self.train(transactions):
                return {
                    'prediction': None,
                    'confidence': 0,
                    'error': 'Insufficient data for prediction'
                }
        
        # Prepare features for last month
        X, _ = self.prepare_features(transactions)
        if X.empty:
            return {
                'prediction': None,
                'confidence': 0,
                'error': 'No recent data available'
            }
        
        # Get last month's features and update month number for next month
        next_month_features = X.iloc[-1:].copy()
        next_month_features['month_num'] = (next_month_features['month_num'] % 12) + 1
        
        # Scale features
        X_scaled = self.scaler.transform(next_month_features)
        
        # Make prediction
        prediction = self.model.predict(X_scaled)[0]
        
        # Calculate confidence score (based on R² score of recent predictions)
        recent_confidence = max(0, min(1, self.model.score(
            self.scaler.transform(X.iloc[-3:]), 
            self.prepare_features(transactions)[1].iloc[-3:]
        )))
        
        return {
            'prediction': round(prediction, 2),
            'confidence': round(recent_confidence * 100, 1),
            'error': None
        }

    def get_category_predictions(self, transactions: List[Transaction]) -> Dict[str, float]:
        """
        Predict expenses by category for next month.
        
        Args:
            transactions: List of Transaction objects
            
        Returns:
            Dict containing category-wise predictions
        """
        if not self.is_trained:
            if not self.train(transactions):
                return {}
        
        X, _ = self.prepare_features(transactions)
        if X.empty:
            return {}
        
        # Get category columns
        category_cols = [col for col in X.columns if col.startswith('cat_')]
        
        # Prepare next month's base features
        next_month_features = X.iloc[-1:].copy()
        next_month_features['month_num'] = (next_month_features['month_num'] % 12) + 1
        
        predictions = {}
        for category in category_cols:
            # Create a separate model for each category
            cat_model = LinearRegression()
            cat_target = pd.Series([row[category] for _, row in X.iterrows()])
            
            if cat_target.sum() > 0:  # Only predict for categories with historical data
                cat_model.fit(self.scaler.transform(X), cat_target)
                pred = cat_model.predict(self.scaler.transform(next_month_features))[0]
                if pred > 0:
                    category_name = category[4:].replace('_', ' & ').title()
                    predictions[category_name] = round(pred, 2)
        
        return predictions 