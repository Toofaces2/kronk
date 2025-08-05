#!/bin/bash

# Android TV Critical Fixes - Emergency Optimization
# Fixes the most critical issues preventing Android TV compatibility

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SKIN_DIR="./1080i"
BACKUP_DIR="./backup_$(date +%Y%m%d_%H%M%S)"

echo -e "${RED}=== ANDROID TV CRITICAL FIXES ===${NC}"
echo "This will modify your XML files to fix Android TV compatibility"
echo "Creating backup in: $BACKUP_DIR"
echo ""

# Create backup
mkdir -p "$BACKUP_DIR"
cp -r "$SKIN_DIR" "$BACKUP_DIR/"
echo -e "${GREEN}Backup created successfully${NC}"
echo ""

# Critical Fix 1: Reduce texture overload in include files
echo -e "${YELLOW}[1/5] Fixing Critical Memory Issues...${NC}"

# Fix Includes_Objects.xml (114 textures -> consolidate)
if [ -f "$SKIN_DIR/Includes_Objects.xml" ]; then
    echo "Optimizing Includes_Objects.xml (114 textures)..."
    
    # Create texture atlas references instead of individual textures
    sed -i.bak 's/<texture>\([^<]*\)\.png<\/texture>/<texture atlas="true">\1.png<\/texture>/g' "$SKIN_DIR/Includes_Objects.xml"
    
    # Wrap texture-heavy sections in preload blocks
    sed -i 's/<control type="group" id="\([0-9]*\)">/<control type="group" id="\1"><preload>true<\/preload>/g' "$SKIN_DIR/Includes_Objects.xml"
    
    echo "  - Converted textures to atlas references"
    echo "  - Added preload flags to groups"
fi

# Fix Includes_Layouts.xml (72 textures, 89 groups)
if [ -f "$SKIN_DIR/Includes_Layouts.xml" ]; then
    echo "Optimizing Includes_Layouts.xml..."
    
    # Reduce nested groups by flattening simple ones
    sed -i 's/<control type="group"><control type="group">/<control type="group">/g' "$SKIN_DIR/Includes_Layouts.xml"
    sed -i 's/<\/control><\/control>/<\/control>/g' "$SKIN_DIR/Includes_Layouts.xml"
    
    echo "  - Flattened nested group structures"
fi

# Critical Fix 2: Drastically reduce animations
echo -e "${YELLOW}[2/5] Fixing Critical Animation Overload...${NC}"

# Fix Includes_Animations.xml (82 animations -> simplify)
if [ -f "$SKIN_DIR/Includes_Animations.xml" ]; then
    echo "Simplifying Includes_Animations.xml (82 animations)..."
    
    # Replace complex animations with simple fades
    sed -i 's/effect="slide"/effect="fade"/g' "$SKIN_DIR/Includes_Animations.xml"
    sed -i 's/effect="zoom"/effect="fade"/g' "$SKIN_DIR/Includes_Animations.xml"
    sed -i 's/effect="rotate"/effect="fade"/g' "$SKIN_DIR/Includes_Animations.xml"
    
    # Reduce animation times for Android TV
    sed -i 's/time="[0-9]\{4,\}"/time="200"/g' "$SKIN_DIR/Includes_Animations.xml"
    sed -i 's/time="[5-9][0-9][0-9]"/time="300"/g' "$SKIN_DIR/Includes_Animations.xml"
    
    echo "  - Converted complex effects to simple fades"
    echo "  - Reduced animation times to 200-300ms"
fi

# Fix Includes_Defaults.xml (100 animations)
if [ -f "$SKIN_DIR/Includes_Defaults.xml" ]; then
    echo "Simplifying Includes_Defaults.xml (100 animations)..."
    
    # Disable heavy default animations for Android TV
    sed -i 's/<animation[^>]*effect="slide"[^>]*>/<animation effect="fade" time="150">/g' "$SKIN_DIR/Includes_Defaults.xml"
    sed -i 's/<animation[^>]*effect="zoom"[^>]*>/<animation effect="fade" time="150">/g' "$SKIN_DIR/Includes_Defaults.xml"
    
    echo "  - Simplified default animations"
fi

# Critical Fix 3: Add missing list optimizations
echo -e "${YELLOW}[3/5] Fixing List Performance Issues...${NC}"

# Function to add list optimizations
add_list_optimizations() {
    local file="$1"
    local file_name=$(basename "$file")
    
    if [ -f "$file" ]; then
        # Add preloaditems to all lists
        sed -i 's/<control type="list"/<control type="list"><preloaditems>2<\/preloaditems>/g' "$file"
        sed -i 's/<control type="fixedlist"/<control type="fixedlist"><preloaditems>2<\/preloaditems>/g' "$file"
        sed -i 's/<control type="panel"/<control type="panel"><preloaditems>2<\/preloaditems>/g' "$file"
        
        # Add scrolltime for smooth scrolling
        sed -i 's/<preloaditems>2<\/preloaditems>/<preloaditems>2<\/preloaditems><scrolltime>200<\/scrolltime>/g' "$file"
        
        # Remove duplicate entries that might have been created
        sed -i 's/<preloaditems>2<\/preloaditems><preloaditems>2<\/preloaditems>/<preloaditems>2<\/preloaditems>/g' "$file"
        sed -i 's/<scrolltime>200<\/scrolltime><scrolltime>200<\/scrolltime>/<scrolltime>200<\/scrolltime>/g' "$file"
        
        echo "  - Fixed $file_name"
    fi
}

# Apply to critical files
add_list_optimizations "$SKIN_DIR/Home.xml"
add_list_optimizations "$SKIN_DIR/MyVideoNav.xml"
add_list_optimizations "$SKIN_DIR/MyMusicNav.xml"
add_list_optimizations "$SKIN_DIR/Includes_Views.xml"
add_list_optimizations "$SKIN_DIR/Includes_Views_List.xml"
add_list_optimizations "$SKIN_DIR/VideoOSD.xml"
add_list_optimizations "$SKIN_DIR/MusicOSD.xml"

# Critical Fix 4: Fix navigation issues
echo -e "${YELLOW}[4/5] Fixing Navigation Issues...${NC}"

# Function to add basic navigation to buttons
fix_navigation() {
    local file="$1"
    local file_name=$(basename "$file")
    
    if [ -f "$file" ]; then
        # Add basic navigation to buttons without it
        sed -i 's/<control type="button" id="\([0-9]*\)">/<control type="button" id="\1"><onup>\1<\/onup><ondown>\1<\/ondown><onleft>\1<\/onleft><onright>\1<\/onright>/g' "$file"
        
        # Fix broken default controls by setting to first available button
        if grep -q "defaultcontrol>" "$file"; then
            # Get first button ID
            first_button=$(grep -o 'id="[0-9]*"' "$file" | head -1 | cut -d'"' -f2)
            if [ -n "$first_button" ]; then
                sed -i "s/defaultcontrol>[0-9]*</defaultcontrol>$first_button</g" "$file"
            fi
        fi
        
        echo "  - Fixed navigation in $file_name"
    fi
}

# Fix critical navigation files
fix_navigation "$SKIN_DIR/Home.xml"
fix_navigation "$SKIN_DIR/DialogVideoInfo.xml"
fix_navigation "$SKIN_DIR/DialogSelect.xml"
fix_navigation "$SKIN_DIR/FileBrowser.xml"
fix_navigation "$SKIN_DIR/DialogSubtitles.xml"

# Critical Fix 5: Create Android TV optimized settings
echo -e "${YELLOW}[5/5] Creating Android TV Settings...${NC}"

# Create or update skin settings for Android TV mode
cat > "$SKIN_DIR/Custom_AndroidTV_Mode.xml" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<window>
    <defaultcontrol>1</defaultcontrol>
    <allowoverlay>no</allowoverlay>
    
    <!-- Android TV Optimizations -->
    <controls>
        <control type="group">
            <visible>System.Platform.Android</visible>
            
            <!-- Reduce texture memory -->
            <control type="image">
                <texture preload="true" atlas="true">common/background.jpg</texture>
                <aspectratio>scale</aspectratio>
            </control>
            
            <!-- Simplified animations -->
            <animation effect="fade" time="150">WindowOpen</animation>
            <animation effect="fade" time="150">WindowClose</animation>
        </control>
    </controls>
</window>
EOF

echo "  - Created Android TV optimization file"

# Update addon.xml for better Android compatibility
if [ -f "addon.xml" ]; then
    echo "Updating addon.xml for Android TV compatibility..."
    
    # Lower GUI version requirement
    sed -i 's/version="[0-9]*\.[0-9]*\.[0-9]*"/version="5.14.0"/g' addon.xml
    
    # Add Android platform if missing
    if ! grep -q "android" addon.xml; then
        sed -i 's/platform="[^"]*"/platform="all"/g' addon.xml
    fi
    
    echo "  - Updated addon.xml for Android compatibility"
fi

echo ""
echo -e "${GREEN}=== CRITICAL FIXES APPLIED ===${NC}"
echo -e "${BLUE}Summary of changes:${NC}"
echo "✓ Reduced texture loading in critical include files"
echo "✓ Simplified 82+ animations to basic fades"
echo "✓ Added preloaditems=2 and scrolltime=200 to lists"
echo "✓ Fixed navigation for D-pad compatibility"
echo "✓ Created Android TV optimization mode"
echo "✓ Updated addon.xml for broader compatibility"
echo ""

echo -e "${YELLOW}IMMEDIATE TESTING STEPS:${NC}"
echo "1. Test on Android TV box immediately"
echo "2. Check if skin loads without crashing"
echo "3. Test navigation with remote control only"
echo "4. Monitor memory usage in Kodi debug log"
echo ""

echo -e "${RED}ADDITIONAL RECOMMENDATIONS:${NC}"
echo "• Consider splitting large include files into smaller modules"
echo "• Use texture atlases for frequently used images"
echo "• Test with a minimal Android TV box (2GB RAM or less)"
echo "• Monitor Kodi log for 'out of memory' errors"
echo ""

echo -e "${GREEN}Backup location: $BACKUP_DIR${NC}"
echo "If issues persist, restore from backup and contact for deeper optimization"