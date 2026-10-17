-- Optional manual migration. main.py runs the same additive migration after
-- successful user authentication. Existing course-project tables stay intact.
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id INT PRIMARY KEY,
    preferences TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
