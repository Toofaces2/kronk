#!/bin/bash

# Arctic Horizon 2.1 - Complete Cache Analysis Script
# Analyzes all 1080i XML files for caching optimization opportunities

SKIN_DIR="1080i"
OUTPUT_FILE="cache_analysis_report.txt"
TEMP_FILE="/tmp/cache_temp.txt"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}=== Arctic Horizon 2.1 - Complete Cache Analysis ===${NC}"
echo "Analyzing directory: $SKIN_DIR"
echo "Report will be saved to: $OUTPUT_FILE"
echo ""

# Check if directory exists
if [ ! -d "$SKIN_DIR" ]; then
    echo -e "${RED}Error: Directory $SKIN_DIR not found!${NC}"
    exit 1
fi

# Initialize report
cat > "$OUTPUT_FILE" << EOF
ARCTIC HORIZON 2.1 - COMPLETE CACHE ANALYSIS REPORT
Generated: $(date)
Directory: $SKIN_DIR

==============================================
SUMMARY STATISTICS
==============================================

EOF

# Initialize counters
total_files=0
total_expressions=0
cached_expressions=0
uncached_expressions=0
total_infos=0
cached_infos=0
total_visibles=0
cached_visibles=0
total_enables=0
cached_enables=0

echo -e "${YELLOW}Scanning XML files...${NC}"

# Find all XML files and analyze them
find "$SKIN_DIR" -name "*.xml" -type f | while read -r file; do
    filename=$(basename "$file")
    echo "  Processing: $filename"
    
    # Count different types of expressions
    file_expressions=$(grep -c '\$INFO\|\$VAR\|\$LOCALIZE\|\$ADDON\|\$ESCINFO' "$file" 2>/dev/null || echo 0)
    file_cached=$(grep -c '\$VAR\[' "$file" 2>/dev/null || echo 0)
    file_uncached=$((file_expressions - file_cached))
    
    file_infos=$(grep -c '\$INFO\[' "$file" 2>/dev/null || echo 0)
    file_cached_infos=$(grep -c '\$VAR\[.*INFO' "$file" 2>/dev/null || echo 0)
    
    file_visibles=$(grep -c 'visible=' "$file" 2>/dev/null || echo 0)
    file_cached_visibles=$(grep -c 'visible="\$VAR\[' "$file" 2>/dev/null || echo 0)
    
    file_enables=$(grep -c 'enable=' "$file" 2>/dev/null || echo 0)
    file_cached_enables=$(grep -c 'enable="\$VAR\[' "$file" 2>/dev/null || echo 0)
    
    # Write detailed file analysis
    cat >> "$OUTPUT_FILE" << EOF

FILE: $filename
----------------------------------------
Total Expressions: $file_expressions
Cached (VAR): $file_cached
Uncached: $file_uncached
Cache Ratio: $(( file_expressions > 0 ? (file_cached * 100) / file_expressions : 0 ))%

INFO Expressions: $file_infos
Cached INFOs: $file_cached_infos

Visible Conditions: $file_visibles  
Cached Visibles: $file_cached_visibles

Enable Conditions: $file_enables
Cached Enables: $file_cached_enables

EOF

    # Add to totals (use temporary file since we're in a subshell)
    echo "$file_expressions $file_cached $file_uncached $file_infos $file_cached_infos $file_visibles $file_cached_visibles $file_enables $file_cached_enables" >> "$TEMP_FILE"
    
done

echo -e "${YELLOW}Analyzing uncached expressions...${NC}"

# Calculate totals from temp file
if [ -f "$TEMP_FILE" ]; then
    while read -r expr cached uncached infos cached_infos visibles cached_visibles enables cached_enables; do
        total_files=$((total_files + 1))
        total_expressions=$((total_expressions + expr))
        cached_expressions=$((cached_expressions + cached))
        uncached_expressions=$((uncached_expressions + uncached))
        total_infos=$((total_infos + infos))
        cached_infos=$((cached_infos + cached_infos))
        total_visibles=$((total_visibles + visibles))
        cached_visibles=$((cached_visibles + cached_visibles))
        total_enables=$((total_enables + enables))
        cached_enables=$((cached_enables + cached_enables))
    done < "$TEMP_FILE"
    rm "$TEMP_FILE"
fi

# Calculate percentages
if [ $total_expressions -gt 0 ]; then
    cache_percentage=$(( (cached_expressions * 100) / total_expressions ))
else
    cache_percentage=0
fi

if [ $total_infos -gt 0 ]; then
    info_cache_percentage=$(( (cached_infos * 100) / total_infos ))
else
    info_cache_percentage=0
fi

if [ $total_visibles -gt 0 ]; then
    visible_cache_percentage=$(( (cached_visibles * 100) / total_visibles ))
else
    visible_cache_percentage=0
fi

if [ $total_enables -gt 0 ]; then
    enable_cache_percentage=$(( (cached_enables * 100) / total_enables ))
else
    enable_cache_percentage=0
fi

# Update summary in report
sed -i '/^SUMMARY STATISTICS/,/^==============================================$/c\
SUMMARY STATISTICS\
==============================================\
\
Total XML Files Analyzed: '$total_files'\
Total Expressions Found: '$total_expressions'\
Cached Expressions (VAR): '$cached_expressions'\
Uncached Expressions: '$uncached_expressions'\
Overall Cache Ratio: '$cache_percentage'%\
\
INFO Expressions: '$total_infos'\
Cached INFO Expressions: '$cached_infos'\
INFO Cache Ratio: '$info_cache_percentage'%\
\
Visible Conditions: '$total_visibles'\
Cached Visible Conditions: '$cached_visibles'\
Visible Cache Ratio: '$visible_cache_percentage'%\
\
Enable Conditions: '$total_enables'\
Cached Enable Conditions: '$cached_enables'\
Enable Cache Ratio: '$enable_cache_percentage'%\
\
==============================================\
OPTIMIZATION OPPORTUNITIES\
==============================================' "$OUTPUT_FILE"

echo -e "${YELLOW}Finding specific optimization opportunities...${NC}"

# Find specific uncached patterns
cat >> "$OUTPUT_FILE" << EOF

UNCACHED PATTERNS TO OPTIMIZE:
---------------------------------------------
EOF

# Find common uncached INFO patterns
echo "Most Common Uncached INFO Patterns:" >> "$OUTPUT_FILE"
find "$SKIN_DIR" -name "*.xml" -exec grep -H '\$INFO\[' {} \; | \
    grep -v '\$VAR\[' | \
    sed 's/.*\$INFO\[\([^]]*\)\].*/\1/' | \
    sort | uniq -c | sort -nr | head -20 >> "$OUTPUT_FILE"

echo "" >> "$OUTPUT_FILE"
echo "Uncached Visible Conditions:" >> "$OUTPUT_FILE"
find "$SKIN_DIR" -name "*.xml" -exec grep -H 'visible="[^$]*\$INFO\[' {} \; | head -10 >> "$OUTPUT_FILE"

echo "" >> "$OUTPUT_FILE"
echo "Files with Most Uncached Expressions:" >> "$OUTPUT_FILE"
find "$SKIN_DIR" -name "*.xml" -exec sh -c 'echo "$(grep -c "\$INFO\[" "$1" | grep -v "\$VAR\[") $1"' _ {} \; | \
    sort -nr | head -10 >> "$OUTPUT_FILE"

# Console output summary
echo ""
echo -e "${GREEN}=== ANALYSIS COMPLETE ===${NC}"
echo -e "${BLUE}Files Analyzed:${NC} $total_files"
echo -e "${BLUE}Total Expressions:${NC} $total_expressions"
echo -e "${GREEN}Cached:${NC} $cached_expressions ($cache_percentage%)"
echo -e "${RED}Uncached:${NC} $uncached_expressions"
echo ""
echo -e "${YELLOW}Optimization Potential:${NC}"
echo -e "  • INFO expressions: ${RED}$((total_infos - cached_infos))${NC} uncached ($info_cache_percentage% cached)"
echo -e "  • Visible conditions: ${RED}$((total_visibles - cached_visibles))${NC} uncached ($visible_cache_percentage% cached)"
echo -e "  • Enable conditions: ${RED}$((total_enables - cached_enables))${NC} uncached ($enable_cache_percentage% cached)"
echo ""

if [ $cache_percentage -lt 80 ]; then
    echo -e "${RED}⚠️  Cache ratio below 80% - significant optimization opportunities available!${NC}"
elif [ $cache_percentage -lt 90 ]; then
    echo -e "${YELLOW}⚠️  Cache ratio below 90% - some optimization opportunities remain${NC}"
else
    echo -e "${GREEN}✅ Cache ratio above 90% - well optimized!${NC}"
fi

echo ""
echo -e "${BLUE}Detailed report saved to: $OUTPUT_FILE${NC}"
echo -e "${BLUE}Use this report to identify files and patterns that need caching optimization.${NC}"