import nuke
import nukescripts
nukescripts.panels.registerWidgetAsPanel('kadatha.start_kadatha', "Kadatha", 'com.Headshift.Kadatha', True)

# --- Tools ---
nuke.menu("Nuke").addCommand('Viewer/Kadatha', 'import kadatha; nukescripts.panels.restorePanel("com.Headshift.Kadatha")')
