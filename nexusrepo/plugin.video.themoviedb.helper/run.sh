#!/bin/bash

# TMDbHelper Import Chain Analyzer - Find the True Foundation
# This finds what gets imported first and most frequently

ADDON_ROOT="$(pwd)"
REPORT_FILE="import_analysis_$(date +%Y%m%d_%H%M%S).md"

echo "# TMDbHelper Import Chain Analysis" > $REPORT_FILE
echo "## Finding the True Foundation Files" >> $REPORT_FILE
echo "" >> $REPORT_FILE

echo "🔍 Analyzing TMDbHelper import dependencies..."

# 1. Find the entry points
echo "## Entry Points (What Kodi Calls First)" >> $REPORT_FILE
echo "" >> $REPORT_FILE

for entry in plugin.py script.py service.py; do
    if [ -f "resources/$entry" ]; then
        echo "### resources/$entry" >> $REPORT_FILE
        echo '```python' >> $REPORT_FILE
        head -20 "resources/$entry" >> $REPORT_FILE
        echo '```' >> $REPORT_FILE
        echo "" >> $REPORT_FILE
    fi
done

# 2. Find most imported modules
echo "## Most Imported Modules (The Real Foundation)" >> $REPORT_FILE
echo "" >> $REPORT_FILE

echo "Analyzing import frequency..." 
find "$ADDON_ROOT/resources" -name "*.py" -exec grep -h "^from tmdbhelper\|^import tmdbhelper" {} \; | \
sed 's/from tmdbhelper\.lib\.//' | \
sed 's/import tmdbhelper\.lib\.//' | \
sed 's/ import.*$//' | \
sort | uniq -c | sort -nr > temp_imports.txt

echo "**Import Frequency Analysis:**" >> $REPORT_FILE
echo '```' >> $REPORT_FILE
head -20 temp_imports.txt >> $REPORT_FILE
echo '```' >> $REPORT_FILE
echo "" >> $REPORT_FILE

# 3. Find base classes that everything inherits from
echo "## Base Classes (What Everything Inherits From)" >> $REPORT_FILE
echo "" >> $REPORT_FILE

find "$ADDON_ROOT/resources" -name "*.py" -exec grep -l "class.*:" {} \; | while read file; do
    classes=$(grep "^class " "$file" | head -5)
    if [ ! -z "$classes" ]; then
        relative_path="${file#$ADDON_ROOT/}"
        echo "### $relative_path" >> $REPORT_FILE
        echo '```python' >> $REPORT_FILE
        echo "$classes" >> $REPORT_FILE
        echo '```' >> $REPORT_FILE
        echo "" >> $REPORT_FILE
    fi
done

# 4. Find addon core dependencies
echo "## Addon Core Dependencies (The Foundation)" >> $REPORT_FILE
echo "" >> $REPORT_FILE

if [ -d "resources/tmdbhelper/lib/addon" ]; then
    echo "### tmdbhelper.lib.addon contents:" >> $REPORT_FILE
    for file in resources/tmdbhelper/lib/addon/*.py; do
        if [ -f "$file" ]; then
            filename=$(basename "$file" .py)
            imports=$(grep -c "from\|import" "$file" 2>/dev/null || echo "0")
            echo "- **$filename.py** ($imports imports)" >> $REPORT_FILE
        fi
    done
    echo "" >> $REPORT_FILE
fi

# 5. Find initialization order
echo "## Initialization Order Analysis" >> $REPORT_FILE
echo "" >> $REPORT_FILE

echo "### Files that import settings/logging first (true foundation):" >> $REPORT_FILE
grep -l "get_setting\|kodi_log" resources/tmdbhelper/lib/addon/*.py | while read file; do
    relative_path="${file#$ADDON_ROOT/}"
    echo "- $relative_path" >> $REPORT_FILE
done
echo "" >> $REPORT_FILE

# 6. Find the minimal working set
echo "## Minimal Working Set (What You Need for Basic Function)" >> $REPORT_FILE
echo "" >> $REPORT_FILE

echo "### Files imported by entry points:" >> $REPORT_FILE
for entry in plugin.py script.py service.py; do
    if [ -f "resources/$entry" ]; then
        echo "#### $entry imports:" >> $REPORT_FILE
        grep "^from tmdbhelper\|^import tmdbhelper" "resources/$entry" >> $REPORT_FILE 2>/dev/null || echo "No tmdbhelper imports found" >> $REPORT_FILE
        echo "" >> $REPORT_FILE
    fi
done

# Clean up
rm -f temp_imports.txt

echo "📊 Import analysis complete! Report saved to: $REPORT_FILE"
echo ""
echo "🎯 PRIORITY: Look at these files first:"
echo "   1. resources/plugin.py, script.py, service.py (entry points)"
echo "   2. tmdbhelper.lib.addon.* (foundation modules)" 
echo "   3. Most imported modules from the frequency analysis"

# Open report if possible
if command -v cat >/dev/null 2>&1; then
    echo ""
    echo "📄 Quick Preview:"
    echo "=================="
    head -30 $REPORT_FILE
fi