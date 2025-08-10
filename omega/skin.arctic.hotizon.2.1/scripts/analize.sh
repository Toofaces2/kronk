#!/bin/bash

# Kodi Skin Cache Optimization Analyzer
# Analyzes XML files in a Kodi skin to identify caching opportunities

set -e

# Colors for output
RED='\033[0;31m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
SKIN_DIR="${1:-./1080i}"
TEMP_DIR="/tmp/kodi_cache_analysis_$$"
DETAILED="${2:-false}"

# Create temp directory
mkdir -p "$TEMP_DIR"

# Cleanup function
cleanup() {
    rm -rf "$TEMP_DIR"
}
trap cleanup EXIT

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  KODI SKIN CACHE OPTIMIZATION ANALYZER${NC}"
echo -e "${BLUE}================================================${NC}"
echo -e "Analyzing skin directory: ${CYAN}$SKIN_DIR${NC}"

if [ ! -d "$SKIN_DIR" ]; then
    echo -e "${RED}Error: Directory '$SKIN_DIR' not found${NC}"
    exit 1
fi

# Find all XML files
XML_FILES=$(find "$SKIN_DIR" -name "*.xml" -type f)
XML_COUNT=$(echo "$XML_FILES" | wc -l)

echo -e "Found ${YELLOW}$XML_COUNT${NC} XML files to analyze"
echo ""

# Analysis functions

analyze_textures() {
    echo -e "${PURPLE}🖼️  ANALYZING TEXTURE USAGE...${NC}"
    
    # Find all texture references and count them
    {
        # Pattern 1: <texture>filename</texture>
        grep -h -oE '<texture[^>]*>[^<]+</texture>' $XML_FILES 2>/dev/null | \
            sed 's/<texture[^>]*>//g; s/<\/texture>//g' | sort | uniq -c | sort -nr
        
        # Pattern 2: texture="filename"
        grep -h -oE 'texture="[^"]*"' $XML_FILES 2>/dev/null | \
            sed 's/texture="//g; s/"//g' | sort | uniq -c | sort -nr
            
        # Pattern 3: <icon>filename</icon>
        grep -h -oE '<icon[^>]*>[^<]+</icon>' $XML_FILES 2>/dev/null | \
            sed 's/<icon[^>]*>//g; s/<\/icon>//g' | sort | uniq -c | sort -nr
            
        # Pattern 4: icon="filename"
        grep -h -oE 'icon="[^"]*"' $XML_FILES 2>/dev/null | \
            sed 's/icon="//g; s/"//g' | sort | uniq -c | sort -nr
    } | awk '{count[$2] += $1} END {for (texture in count) print count[texture], texture}' | \
      sort -nr > "$TEMP_DIR/texture_usage.txt"
    
    # Top textures
    echo -e "  ${YELLOW}Top 15 most used textures (prime caching candidates):${NC}"
    head -15 "$TEMP_DIR/texture_usage.txt" | while read count texture; do
        if [ "$count" -gt 5 ]; then
            echo -e "    ${RED}$count${NC}x  $texture"
        elif [ "$count" -gt 2 ]; then
            echo -e "    ${YELLOW}$count${NC}x  $texture"
        else
            echo -e "    ${GREEN}$count${NC}x  $texture"
        fi
    done
    
    # Find duplicate textures per file
    echo -e "  ${YELLOW}Files with duplicate texture usage:${NC}"
    for file in $XML_FILES; do
        filename=$(basename "$file")
        duplicates=$(grep -oE '<texture[^>]*>[^<]+</texture>|texture="[^"]*"|<icon[^>]*>[^<]+</icon>|icon="[^"]*"' "$file" 2>/dev/null | \
                    sed 's/<texture[^>]*>//g; s/<\/texture>//g; s/texture="//g; s/"//g; s/<icon[^>]*>//g; s/<\/icon>//g; s/icon="//g' | \
                    sort | uniq -c | awk '$1 > 1 {print $1 "x " $2}')
        if [ -n "$duplicates" ]; then
            echo -e "    ${CYAN}$filename:${NC}"
            echo "$duplicates" | head -5 | sed 's/^/      /'
        fi
    done
    echo ""
}

analyze_includes() {
    echo -e "${PURPLE}📦 ANALYZING INCLUDE USAGE...${NC}"
    
    # Count include usage across all files
    grep -h -oE '<include[^>]*>[^<]+</include>' $XML_FILES 2>/dev/null | \
        sed 's/<include[^>]*>//g; s/<\/include>//g' | \
        sort | uniq -c | sort -nr > "$TEMP_DIR/include_usage.txt"
    
    echo -e "  ${YELLOW}Most used includes:${NC}"
    head -15 "$TEMP_DIR/include_usage.txt" | while read count include; do
        if [ "$count" -gt 10 ]; then
            echo -e "    ${RED}$count${NC}x  $include"
        elif [ "$count" -gt 5 ]; then
            echo -e "    ${YELLOW}$count${NC}x  $include"
        else
            echo -e "    ${GREEN}$count${NC}x  $include"
        fi
    done
    
    # Files with heavy include usage
    echo -e "  ${YELLOW}Files with heavy include usage (>10 includes):${NC}"
    for file in $XML_FILES; do
        filename=$(basename "$file")
        include_count=$(grep -c '<include[^>]*>[^<]' "$file" 2>/dev/null || echo 0)
        if [ "$include_count" -gt 10 ]; then
            unique_includes=$(grep -oE '<include[^>]*>[^<]+</include>' "$file" 2>/dev/null | \
                            sed 's/<include[^>]*>//g; s/<\/include>//g' | sort -u | wc -l)
            echo -e "    ${CYAN}$filename:${NC} ${include_count} includes (${unique_includes} unique)"
        fi
    done
    echo ""
}

analyze_variables() {
    echo -e "${PURPLE}🔧 ANALYZING VARIABLE USAGE...${NC}"
    
    # Find all variable references
    {
        grep -h -oE '\$VAR\[[^\]]+\]' $XML_FILES 2>/dev/null | sort | uniq -c | sort -nr
        grep -h -oE '\$INFO\[[^\]]+\]' $XML_FILES 2>/dev/null | sort | uniq -c | sort -nr  
        grep -h -oE '\$LOCALIZE\[[^\]]+\]' $XML_FILES 2>/dev/null | sort | uniq -c | sort -nr
    } > "$TEMP_DIR/variable_usage.txt"
    
    echo -e "  ${YELLOW}Most used variables:${NC}"
    head -15 "$TEMP_DIR/variable_usage.txt" | while read count variable; do
        if [ "$count" -gt 15 ]; then
            echo -e "    ${RED}$count${NC}x  $variable"
        elif [ "$count" -gt 5 ]; then
            echo -e "    ${YELLOW}$count${NC}x  $variable"
        else
            echo -e "    ${GREEN}$count${NC}x  $variable"
        fi
    done
    echo ""
}

analyze_conditions() {
    echo -e "${PURPLE}❓ ANALYZING CONDITION USAGE...${NC}"
    
    # Extract conditions from visible and condition attributes
    {
        grep -h -oE '<visible>[^<]+</visible>' $XML_FILES 2>/dev/null | \
            sed 's/<visible>//g; s/<\/visible>//g'
        grep -h -oE 'condition="[^"]*"' $XML_FILES 2>/dev/null | \
            sed 's/condition="//g; s/"//g'
        grep -h -oE '<enable>[^<]+</enable>' $XML_FILES 2>/dev/null | \
            sed 's/<enable>//g; s/<\/enable>//g'
    } | sort | uniq -c | sort -nr > "$TEMP_DIR/condition_usage.txt"
    
    echo -e "  ${YELLOW}Most used conditions:${NC}"
    head -10 "$TEMP_DIR/condition_usage.txt" | while read count condition; do
        # Truncate long conditions
        display_condition=$(echo "$condition" | cut -c1-60)
        if [ ${#condition} -gt 60 ]; then
            display_condition="$display_condition..."
        fi
        
        if [ "$count" -gt 5 ]; then
            echo -e "    ${RED}$count${NC}x  $display_condition"
        elif [ "$count" -gt 2 ]; then
            echo -e "    ${YELLOW}$count${NC}x  $display_condition"
        else
            echo -e "    ${GREEN}$count${NC}x  $display_condition"
        fi
    done
    
    # Complex conditions (potential caching candidates)
    echo -e "  ${YELLOW}Complex conditions (consider caching as variables):${NC}"
    grep -h -oE '<visible>[^<]+</visible>|condition="[^"]*"|<enable>[^<]+</enable>' $XML_FILES 2>/dev/null | \
        sed 's/<visible>//g; s/<\/visible>//g; s/condition="//g; s/"//g; s/<enable>//g; s/<\/enable>//g' | \
        awk 'length($0) > 50 && ($0 ~ /\+/ || $0 ~ /\|/ || $0 ~ /!/)' | \
        sort | uniq -c | sort -nr | head -5 | while read count condition; do
            display_condition=$(echo "$condition" | cut -c1-70)
            if [ ${#condition} -gt 70 ]; then
                display_condition="$display_condition..."
            fi
            echo -e "    ${RED}$count${NC}x  $display_condition"
        done
    echo ""
}

analyze_heavy_operations() {
    echo -e "${PURPLE}⚡ ANALYZING HEAVY OPERATIONS...${NC}"
    
    echo -e "  ${YELLOW}Files with potentially heavy operations:${NC}"
    
    for file in $XML_FILES; do
        filename=$(basename "$file")
        operations=()
        
        # Check for various heavy operations
        container_content=$(grep -c "Container\.Content" "$file" 2>/dev/null || echo 0)
        listitem_count=$(grep -c "ListItem\." "$file" 2>/dev/null || echo 0)
        hasaddon_count=$(grep -c "System\.HasAddon" "$file" 2>/dev/null || echo 0)
        hassetting_count=$(grep -c "Skin\.HasSetting" "$file" 2>/dev/null || echo 0)
        
        if [ "$container_content" -gt 0 ]; then
            operations+=("Container.Content: $container_content")
        fi
        if [ "$listitem_count" -gt 20 ]; then
            operations+=("Heavy ListItem usage: $listitem_count")
        fi
        if [ "$hasaddon_count" -gt 0 ]; then
            operations+=("HasAddon checks: $hasaddon_count")
        fi
        if [ "$hassetting_count" -gt 10 ]; then
            operations+=("HasSetting checks: $hassetting_count")
        fi
        
        if [ ${#operations[@]} -gt 0 ]; then
            echo -e "    ${CYAN}$filename:${NC}"
            for op in "${operations[@]}"; do
                echo -e "      • $op"
            done
        fi
    done
    echo ""
}

analyze_file_sizes() {
    echo -e "${PURPLE}📏 ANALYZING FILE SIZES...${NC}"
    
    echo -e "  ${YELLOW}Largest XML files (potential optimization targets):${NC}"
    find "$SKIN_DIR" -name "*.xml" -exec ls -la {} \; | \
        awk '{print $5, $9}' | sort -nr | head -10 | while read size file; do
            filename=$(basename "$file")
            size_kb=$((size / 1024))
            if [ "$size_kb" -gt 50 ]; then
                echo -e "    ${RED}${size_kb}KB${NC}  $filename"
            elif [ "$size_kb" -gt 20 ]; then
                echo -e "    ${YELLOW}${size_kb}KB${NC}  $filename"
            else
                echo -e "    ${GREEN}${size_kb}KB${NC}  $filename"
            fi
        done
    echo ""
}

# Run all analyses
analyze_textures
analyze_includes
analyze_variables
analyze_conditions
analyze_heavy_operations
analyze_file_sizes

# Generate optimization recommendations
echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  OPTIMIZATION RECOMMENDATIONS${NC}"
echo -e "${BLUE}================================================${NC}"

echo -e "${RED}🔴 HIGH PRIORITY:${NC}"
echo -e "  1. ${YELLOW}Texture Preloading:${NC} Cache the top 20 most-used textures"
echo -e "     • Add <preload> tags in Font.xml or create TextureCache.xml"
echo -e "     • Focus on textures used >10 times across files"
echo -e ""
echo -e "  2. ${YELLOW}Complex Expression Caching:${NC} Convert complex conditions to variables"
echo -e "     • Move lengthy conditions to skin variables"
echo -e "     • Use <variable> tags in Includes_Constants.xml"
echo -e ""

echo -e "${YELLOW}🟡 MEDIUM PRIORITY:${NC}"
echo -e "  3. ${YELLOW}Include Consolidation:${NC} Optimize heavily-included files"
echo -e "     • Consider breaking large includes into smaller, cached pieces"
echo -e "     • Group related includes together"
echo -e ""
echo -e "  4. ${YELLOW}Condition Ordering:${NC} Optimize condition evaluation"
echo -e "     • Place most frequently true conditions first"
echo -e "     • Cache expensive system calls"
echo -e ""

echo -e "${GREEN}🟢 LOW PRIORITY:${NC}"
echo -e "  5. ${YELLOW}Container Caching:${NC} Implement smart container updates"
echo -e "     • Use Container.Content caching where possible"
echo -e "     • Minimize ListItem property lookups"
echo -e ""

# Detailed analysis if requested
if [ "$DETAILED" = "true" ] || [ "$2" = "--detailed" ]; then
    echo -e "${BLUE}================================================${NC}"
    echo -e "${BLUE}  DETAILED ANALYSIS${NC}"
    echo -e "${BLUE}================================================${NC}"
    
    echo -e "${CYAN}All texture usage (sorted by frequency):${NC}"
    cat "$TEMP_DIR/texture_usage.txt" | head -30
    echo ""
    
    echo -e "${CYAN}All include usage (sorted by frequency):${NC}"
    cat "$TEMP_DIR/include_usage.txt" | head -20
    echo ""
    
    echo -e "${CYAN}All variable usage (sorted by frequency):${NC}"
    cat "$TEMP_DIR/variable_usage.txt" | head -20
    echo ""
fi

echo -e "${GREEN}Analysis complete!${NC}"
echo -e "For detailed output, run: ${CYAN}$0 $SKIN_DIR --detailed${NC}"