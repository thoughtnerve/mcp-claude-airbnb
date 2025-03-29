# Instructions to Push to GitHub

1. Create a new repository on GitHub:
   - Go to https://github.com/new
   - Name your repository (e.g., "claude-airbnb-tools")
   - Choose public or private
   - Do not initialize with README (since we already have one)
   - Click "Create repository"

2. Add the remote repository:
   ```
   git remote add origin https://github.com/YOUR_USERNAME/claude-airbnb-tools.git
   ```
   Replace `YOUR_USERNAME` with your GitHub username

3. Push your local repository to GitHub:
   ```
   git branch -M main
   git push -u origin main
   ```

4. Verify that your code is now on GitHub by visiting:
   ```
   https://github.com/YOUR_USERNAME/claude-airbnb-tools
   ``` 