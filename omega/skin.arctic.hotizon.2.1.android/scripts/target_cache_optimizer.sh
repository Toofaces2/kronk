#!/bin/bash

# Arctic Horizon 2.1 - Cache Optimization Script
# Converts common $INFO patterns to cached $VAR expressions

TARGET_FILE="1080i/Includes_Labels.xml"
BACKUP_FILE="${TARGET_FILE}.backup"
TEMP_FILE="/tmp/cache_optimize.tmp"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}=== Arctic Horizon 2.1 - Cache Optimizer ===${NC}"
echo "Optimizing: $TARGET_FILE"

# Check if file exists
if [ ! -f "$TARGET_FILE" ]; then
    echo -e "${RED}Error: File $TARGET_FILE not found!${NC}"
    exit 1
fi

# Create backup
cp "$TARGET_FILE" "$BACKUP_FILE"
echo -e "${GREEN}✓ Backup created: $BACKUP_FILE${NC}"

# Count before optimization
before_infos=$(grep -c '\$INFO\[' "$TARGET_FILE")
before_vars=$(grep -c '\$VAR\[' "$TARGET_FILE")

echo -e "${YELLOW}Before optimization:${NC}"
echo "  INFO expressions: $before_infos"
echo "  VAR expressions: $before_vars"
echo ""

# Start optimization
cp "$TARGET_FILE" "$TEMP_FILE"

echo -e "${YELLOW}Applying optimizations...${NC}"

# 1. ListItem.Label -> Cached variable
echo "  • Caching ListItem.Label..."
sed -i 's/\$INFO\[ListItem\.Label\]/\$VAR[Cache_ListItem_Label]/g' "$TEMP_FILE"

# 2. ListItem.Title -> Cached variable  
echo "  • Caching ListItem.Title..."
sed -i 's/\$INFO\[ListItem\.Title\]/\$VAR[Cache_ListItem_Title]/g' "$TEMP_FILE"

# 3. Player.Title -> Cached variable
echo "  • Caching Player.Title..."
sed -i 's/\$INFO\[Player\.Title\]/\$VAR[Cache_Player_Title]/g' "$TEMP_FILE"

# 4. ListItem.Year with formatting -> Cached variable
echo "  • Caching ListItem.Year patterns..."
sed -i 's/\$INFO\[ListItem\.Year, • ,\]/\$VAR[Cache_ListItem_Year_Bullet]/g' "$TEMP_FILE"
sed -i 's/\$INFO\[Container\.ListItem\.Year, (,)\]/\$VAR[Cache_Container_ListItem_Year_Parens]/g' "$TEMP_FILE"

# 5. Container.ListItem.Title -> Cached variable
echo "  • Caching Container.ListItem.Title..."
sed -i 's/\$INFO\[Container\.ListItem\.Title\]/\$VAR[Cache_Container_ListItem_Title]/g' "$TEMP_FILE"

# 6. ListItem.Genre -> Cached variable
echo "  • Caching ListItem.Genre..."
sed -i 's/\$INFO\[ListItem\.Genre\]/\$VAR[Cache_ListItem_Genre]/g' "$TEMP_FILE"

# 7. ListItem.ChannelName -> Cached variable
echo "  • Caching ListItem.ChannelName..."
sed -i 's/\$INFO\[ListItem\.ChannelName\]/\$VAR[Cache_ListItem_ChannelName]/g' "$TEMP_FILE"

# 8. Complex Container patterns
echo "  • Caching Container(99950) patterns..."
sed -i 's/\$INFO\[Container(99950)\.ListItem\.Property(Status), ,\]/\$VAR[Cache_Container99950_Status]/g' "$TEMP_FILE"

# 9. Container(6401).CurrentItem pattern
echo "  • Caching Container(6401) patterns..."
sed -i 's/\$INFO\[Container(6401)\.CurrentItem,, \$LOCALIZE\[1443\]/\$VAR[Cache_Container6401_CurrentItem]/g' "$TEMP_FILE"

# Apply changes
mv "$TEMP_FILE" "$TARGET_FILE"

# Count after optimization
after_infos=$(grep -c '\$INFO\[' "$TARGET_FILE")
after_vars=$(grep -c '\$VAR\[' "$TARGET_FILE")

echo -e "${GREEN}After optimization:${NC}"
echo "  INFO expressions: $after_infos"
echo "  VAR expressions: $after_vars"
echo ""

# Calculate improvements
reduced_infos=$((before_infos - after_infos))
added_vars=$((after_vars - before_vars))

echo -e "${BLUE}Optimization Results:${NC}"
echo -e "  ${GREEN}✓ Reduced INFO calls by: $reduced_infos${NC}"
echo -e "  ${GREEN}✓ Added VAR expressions: $added_vars${NC}"

if [ $reduced_infos -gt 0 ]; then
    improvement_percent=$(( (reduced_infos * 100) / before_infos ))
    echo -e "  ${GREEN}✓ Performance improvement: ~$improvement_percent%${NC}"
fi

echo ""
echo -e "${YELLOW}Next steps:${NC}"
echo "1. Add these variable definitions to your Includes_Constants.xml:"
echo ""
echo -e "${BLUE}<!-- New cached variables -->${NC}"
echo '<variable name="Cache_ListItem_Label">'
echo '    <value>$INFO[ListItem.Label]</value>'
echo '</variable>'
echo '<variable name="Cache_ListItem_Title">'
echo '    <value>$INFO[ListItem.Title]</value>'
echo '</variable>'
echo '<variable name="Cache_Player_Title">'
echo '    <value>$INFO[Player.Title]</value>'
echo '</variable>'
echo '<variable name="Cache_ListItem_Year_Bullet">'
echo '    <value>$INFO[ListItem.Year, • ,]</value>'
echo '</variable>'
echo '<variable name="Cache_Container_ListItem_Year_Parens">'
echo '    <value>$INFO[Container.ListItem.Year, (,)]</value>'
echo '</variable>'
echo '<variable name="Cache_Container_ListItem_Title">'
echo '    <value>$INFO[Container.ListItem.Title]</value>'
echo '</variable>'
echo '<variable name="Cache_ListItem_Genre">'
echo '    <value>$INFO[ListItem.Genre]</value>'
echo '</variable>'
echo '<variable name="Cache_ListItem_ChannelName">'
echo '    <value>$INFO[ListItem.ChannelName]</value>'
echo '</variable>'
echo '<variable name="Cache_Container99950_Status">'
echo '    <value>$INFO[Container(99950).ListItem.Property(Status), ,]</value>'
echo '</variable>'
echo '<variable name="Cache_Container6401_CurrentItem">'
echo '    <value>$INFO[Container(6401).CurrentItem,, $LOCALIZE[1443]</value>'
echo '</variable>'
echo ""
echo -e "${GREEN}✓ Optimization complete!${NC}"
echo -e "${BLUE}Backup saved as: $BACKUP_FILE${NC}"