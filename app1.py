from flask import Flask, request, jsonify, render_template, session
from flask_cors import CORS
import pandas as pd
import random
import os
from collections import defaultdict

app = Flask(__name__)
app.secret_key = 'static-key'
app.config.update({
    'SESSION_COOKIE_SAMESITE': 'Lax',    # default, allows top-level navigations
    'SESSION_COOKIE_SECURE': False,      # OK when not using HTTPS on localhost
    'SESSION_COOKIE_DOMAIN': '127.0.0.1' # binds the cookie to exactly this host
})
# Critical CORS configuration update
#CORS(app, supports_credentials=True, origins=["http://127.0.0.1:5000"])
category_counts = defaultdict(int)
difficulty_counts = defaultdict(int)
type_counts = defaultdict(int)
used_question_id = []

# Configuration
CSV_FILE_PATH = 'questions.csv'
df_questions = pd.DataFrame()

def load_questions_from_csv():
    """Load questions from CSV with robust error handling"""
    global df_questions
    try:
        if not os.path.exists(CSV_FILE_PATH):
            raise FileNotFoundError(f"CSV file not found at {CSV_FILE_PATH}")
        
        df = pd.read_csv(CSV_FILE_PATH)
        # Validate required columns
        required_columns = ['id', 'question', 'category', 'difficulty', 'type']
        if not all(col in df.columns for col in required_columns):
            missing = [col for col in required_columns if col not in df.columns]
            raise ValueError(f"Missing required columns: {missing}")
        
        # Clean and standardize data
        df['category'] = df['category'].astype(str).str.upper().str.strip()
        df['difficulty'] = df['difficulty'].astype(str).str.capitalize().str.strip()
        df['type'] = df['type'].astype(str).str.strip()
        
        # Validate values
        valid_difficulties = ['Easy', 'Medium', 'Hard']
        invalid_diffs = df[~df['difficulty'].isin(valid_difficulties)]
        if not invalid_diffs.empty:
            raise ValueError(f"Invalid difficulty values: {invalid_diffs['difficulty'].unique()}")
        
        df_questions = df
        print(f"Successfully loaded {len(df)} questions")
        return True
        
    except Exception as e:
        print(f"Error loading CSV: {str(e)}")
        df_questions = pd.DataFrame(columns=required_columns)
        return False

# Load questions when starting
if not load_questions_from_csv():
    print("Warning: Starting with empty question bank")

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/test.html')
def test():
    return render_template('test.html')
    
@app.route('/start_test.html')
def start_test():
    test_data = session.get('test_data')
    print(test_data)
    return render_template('start_test.html', data=test_data)

# Add to your existing Flask app
@app.route('/api/generate-test', methods=['POST'])
def generate_test():
    all_questions = df_questions.to_dict('records')
    questions_length = len(all_questions)
    print(questions_length)
    global used_question_id
    """Generate test with quota enforcement and deviation reporting"""
    try:
        if df_questions.empty:
            return jsonify({"error": "No questions available"}), 503

        data = request.get_json()
        
        # Validate input
        required_fields = ['total_questions', 'category_counts', 
                         'difficulty_counts', 'type_counts']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Missing required parameters"}), 400

        total = data['total_questions']
        requested_cats = data['category_counts']
        requested_diffs = data['difficulty_counts']
        requested_types = data['type_counts']
        print(requested_cats.items())
        # Verify quota sums match total
        if (sum(requested_cats.values()) != total or 
            sum(requested_diffs.values()) != total or
            sum(requested_types.values()) != total):
            return jsonify({"error": "Quota sums must match total questions"}), 400

        # Initialize selection process
        selected = []
        remaining = {
            'category': requested_cats.copy(),
            'difficulty': requested_diffs.copy(),
            'type': requested_types.copy()
        }
        
        unused_question_id = [q for q in df_questions.to_dict('records')
                                if q['id'] not in used_question_id
                            ]
        random.shuffle(unused_question_id)
        pool = unused_question_id
        random.shuffle(pool)
        # Track actual counts
        actual_counts = {
            'category': defaultdict(int),
            'difficulty': defaultdict(int),
            'type': defaultdict(int)
        }
        
        # Priority-based selection
        for priority_level in [3, 2, 1]:          
            for q in pool:
                if q in selected:
                    continue
                    
                # Check if category exists in remaining
                cat_exists = q['category'] in remaining['category']
                diff_exists = q['difficulty'] in remaining['difficulty']
                type_exists = q['type'] in remaining['type']
                
                fits_category = cat_exists and remaining['category'][q['category']] > 0
                fits_diff = diff_exists and remaining['difficulty'][q['difficulty']] > 0
                fits_type = type_exists and remaining['type'][q['type']] > 0
                
                # Priority checks
                if priority_level == 3:
                    if not (fits_category and fits_diff and fits_type):
                        continue
                elif priority_level == 2:
                    if not ((fits_category and fits_diff) or 
                           (fits_category and fits_type) or 
                           (fits_diff and fits_type)):
                        continue
                else:  # priority_level == 1
                    if not (fits_category or fits_diff or fits_type):
                        continue
                
                selected.append(q)
                if fits_category:
                    remaining['category'][q['category']] -= 1
                if fits_diff:
                    remaining['difficulty'][q['difficulty']] -= 1
                if fits_type:
                    remaining['type'][q['type']] -= 1
                
                # Update actual counts
                actual_counts['category'][q['category']] += 1
                actual_counts['difficulty'][q['difficulty']] += 1
                actual_counts['type'][q['type']] += 1
                
                if len(selected) >= total:
                    break
                    
            if len(selected) >= total:
                break
        
        new_ids = [q['id'] for q in selected]
        used_question_id.extend(new_ids)
        numbers_used = len(used_question_id)
        print(len(used_question_id))
        # Generate deviation messages
        messages = []
        reset_message = None

        if(numbers_used >= questions_length):
            used_question_id = []
            reset_message = "Question bank has been reset automatically for Next Generation as all questions were used."
            print("🔄 Question pool reset")

        # Category deviations
        for cat, req_count in requested_cats.items():
            act_count = actual_counts['category'].get(cat, 0)
            print(act_count)
            if act_count != req_count:
                if act_count < req_count:
                    messages.append(
                        f"Could only provide {act_count} out of {req_count} "
                        f"{cat} category questions"
                    )
                else:
                    messages.append(
                        f"Provided {act_count} instead of {req_count} "
                        f"{cat} category questions"
                    )
        
        # Difficulty deviations
        for diff, req_count in requested_diffs.items():
            act_count = actual_counts['difficulty'].get(diff, 0)
            if act_count != req_count:
                if act_count < req_count:
                    messages.append(
                        f"Could only provide {act_count} out of {req_count} "
                        f"{diff} difficulty questions"
                    )
                else:
                    messages.append(
                        f"Provided {act_count} instead of {req_count} "
                        f"{diff} difficulty questions"
                    )
        
        # Type deviations
        for q_type, req_count in requested_types.items():
            act_count = actual_counts['type'].get(q_type, 0)
            if act_count != req_count:
                if act_count < req_count:
                    messages.append(
                        f"Could only provide {act_count} out of {req_count} "
                        f"{q_type} type questions"
                    )
                else:
                    messages.append(
                        f"Provided {act_count} instead of {req_count} "
                        f"{q_type} type questions"
                    )
        # Prepare response
        response = {
            'test': [{
                'id': q['id'],
                'question': q['question'],
                'category': q['category'],
                'difficulty': q['difficulty'],
                'type': q['type']
            } for q in selected],
            'messages': messages,
            'resetMessages': reset_message
        }
        #print(response['test'])
        session['test_data'] = response['test']
        return jsonify(response)

    except Exception as e:
        print(f"Error generating test: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

@app.route('/check-session')
def check_session():
    return {'session': dict(session)}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
    