set encoding utf8
set terminal qt enhanced title 'sample_1' font 'Malgun Gothic,11' 
set xrange [-50.0035:1050.0735]
set yrange [-300:200]
unset link y2
set y2range [-0.25:1]
set xtics auto
set ytics 100
set y2tics 0.25
unset mxtics
unset mytics
unset my2tics
set grid xtics ytics lw 1.5, lw 1.0
set mouse
set border lw 1.5
set tics scale 1.0, 0.5
set xtics font 'Malgun Gothic,9'
set ytics font 'Malgun Gothic,9'
set y2tics font 'Malgun Gothic,9'
set title "sample" font "Malgun Gothic,14" noenhanced
set xlabel "PRESS:PRSTNK(1)" font "Malgun Gothic,11" noenhanced
set ylabel "var_2" font "Malgun Gothic,11" noenhanced
set y2label "TANK_LEV:PRSTNK" font "Malgun Gothic,11" noenhanced
set ytics nomirror
set rmargin at screen 0.88
set key enhanced inside right top box linewidth 1.5 opaque font "Malgun Gothic,9" samplen 2.5 spacing 1.2
plot \
"D:/CathPlot/sample.dat" using ($1+0.0):3 title "var_2" noenhanced axes x1y1 with lines lw 1.5 lc rgb "black" dt 1, \
"D:/CathPlot/data/out111.dat" using ($1+0.0):12 title "MFLO:R-FWP1>L-SSP1" noenhanced axes x1y1 with lines lw 1.5 lc rgb "red" dt 2, \
"D:/CathPlot/data/out111.dat" using ($1+0.0):13 title "MFLO:R-SDRT1>L-STLF1" noenhanced axes x1y1 with lines lw 1.5 lc rgb "blue" dt 3, \
"D:/CathPlot/data/out111.dat" using ($1+0.0):2 title "TANK_LEV:PRSTNK" noenhanced axes x1y2 with lines lw 1.5 lc rgb "green" dt 4, \
"D:/CathPlot/data/out111.dat" using ($1+0.0):3 title "PLC" noenhanced axes x1y2 with lines lw 1.5 lc rgb "magenta" dt 5

pause mouse close