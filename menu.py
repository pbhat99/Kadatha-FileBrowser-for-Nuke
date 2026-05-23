import nuke
import nukescripts
nukescripts.panels.registerWidgetAsPanel('kadatha.start_kadatha', "Kadatha", 'com.Headshift.Kadatha', True)

# --- Studio Tools ---
nuke.menu("Nuke").addCommand('Viewer/Kadatha', 'import kadatha; nukescripts.panels.restorePanel("com.Headshift.Kadatha")')
#uke.menu("Nuke").addCommand('Viewer/Kadatha', 'import kadatha; nukescripts.panels.restorePanel("com.Headshift.Kadatha")')
 
#toolbar = nuke.toolbar("Nodes")
#toolbar.addCommand("zebuFX/tools/Kadatha", 'import kadatha; nukescripts.panels.restorePanel("com.Headshift.Kadatha")', icon='zb.png')
