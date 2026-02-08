import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from matplotlib.ticker import FuncFormatter
import matplotlib.cm as cm
import matplotlib.colors as mcolors

# 1. Create the dataset
data = {
    'DECLARATIE': ['D112'] * 6 + ['D205'] * 6 + ['D208'] * 6 + ['D209'] * 6 + ['D224'] * 6 + ['DUF'] * 6 + ['RIF'] * 6,
    'AN': [2020, 2021, 2022, 2023, 2024, 2025] * 7,
    'VALOARE': [
        33144245, 42161299, 55446002, 70064847, 78614782, 41891341,  # D112
        6626765, 12234906, 42060273, 21720723, 40100216, 0,  # D205
        176130, 516433, 914965, 1866181, 819931, 938187,  # D208
        0, 0, 0, 0, 1360, 0,  # D209
        8340833, 10559396, 12871285, 13427795, 14073471, 10282837,  # D224
        7597524, 27488343, 23541978, 28490147, 32022403, 0,  # DUF
        0, 163808, 943470, 0, 0, 0  # RIF
    ]
}

df = pd.DataFrame(data)

# 2. Define Groups
top_row_decls = ['D112', 'D205', 'D224', 'DUF']
bottom_row_decls = ['D208', 'RIF', 'D209']

# 3. Setup the Figure and Colormap
sns.set_style("white")
fig, axes = plt.subplots(2, 4, figsize=(18, 10), sharex=False, sharey='row')

# --- COLOR STRATEGY ---
# Use a sequential map: 'YlGnBu' goes from light yellow to dark blue
cmap = cm.get_cmap('YlGnBu')

# Calculate Max values per ROW to normalize colors appropriately
# This ensures the bottom row (Thousands) isn't washed out by the top row (Millions)
top_max = df[df['DECLARATIE'].isin(top_row_decls)]['VALOARE'].max()
bottom_max = df[df['DECLARATIE'].isin(bottom_row_decls)]['VALOARE'].max()

# Create Normalization objects
norm_top = mcolors.Normalize(vmin=0, vmax=top_max)
norm_bottom = mcolors.Normalize(vmin=0, vmax=bottom_max)

# --- PLOT TOP ROW ---
for i, decl in enumerate(top_row_decls):
    ax = axes[0, i]
    subset = df[df['DECLARATIE'] == decl]

    # Generate colors for this specific subset based on the TOP row normalization
    bar_colors = [cmap(norm_top(val)) for val in subset['VALOARE']]

    # Pass the calculated colors to 'palette'
    sns.barplot(data=subset, x='AN', y='VALOARE', palette=bar_colors, ax=ax)

    ax.set_title(decl, fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.set_ylabel('')

    # Formatter
    if i == 0:
        ax.yaxis.set_major_formatter(FuncFormatter(lambda x, pos: '%1.0fM' % (x * 1e-6)))

    # Separation Lines
    if i > 0:
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='y', left=False)

    ax.spines['right'].set_visible(True)
    ax.spines['right'].set_color('black')
    ax.spines['right'].set_linewidth(1.5)

# --- PLOT BOTTOM ROW ---
for i, decl in enumerate(bottom_row_decls):
    ax = axes[1, i]
    subset = df[df['DECLARATIE'] == decl]

    # Generate colors based on the BOTTOM row normalization
    bar_colors = [cmap(norm_bottom(val)) for val in subset['VALOARE']]

    sns.barplot(data=subset, x='AN', y='VALOARE', palette=bar_colors, ax=ax)

    ax.set_title(decl, fontsize=14, fontweight='bold')
    ax.set_xlabel('')
    ax.set_ylabel('')

    # Formatter
    if i == 0:
        def custom_fmt(x, pos):
            if x >= 1_000_000:
                return '%1.1fM' % (x * 1e-6)
            elif x >= 1000:
                return '%1.0fK' % (x * 1e-3)
            else:
                return '%1.0f' % x


        ax.yaxis.set_major_formatter(FuncFormatter(custom_fmt))

    # Separation Lines
    if i > 0:
        ax.spines['left'].set_visible(False)
        ax.tick_params(axis='y', left=False)

    ax.spines['right'].set_visible(True)
    ax.spines['right'].set_color('black')
    ax.spines['right'].set_linewidth(1.5)

# Turn off the empty chart
axes[1, 3].axis('off')

# 5. Final Adjustments
fig.suptitle('Value by Declaration', fontsize=20, y=0.98)
fig.text(0.005, 0.75, 'Millions (M)', va='center', rotation='vertical', fontsize=12, fontweight='bold')
fig.text(0.005, 0.25, 'Thousands (K)', va='center', rotation='vertical', fontsize=12, fontweight='bold')

# Create a manual colorbar legend to explain the intensity
sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(0, 1))
sm.set_array([])
cbar_ax = fig.add_axes([0.92, 0.15, 0.02, 0.7])  # Position: [left, bottom, width, height]
cbar = fig.colorbar(sm, cax=cbar_ax)
cbar.set_label('Relative Intensity (Low to High)', rotation=270, labelpad=15)

plt.tight_layout(rect=[0.02, 0, 0.90, 0.95])
plt.subplots_adjust(wspace=0, hspace=0.3)

plt.show()