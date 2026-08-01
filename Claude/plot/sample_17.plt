set encoding utf8
set terminal windows title 'sample_17' font 'Malgun Gothic,11' size 840,672
set autoscale x
set yrange [-1.75:36.75]
unset link y2
set y2range [-18.5:388.5]
set xtics auto
set ytics 10
set y2tics 100
set mxtics 5
set mytics 5
set my2tics 5
set grid xtics ytics lw 1.5, lw 1.0
set mouse
set border lw 1.5
set lmargin at screen 0.15
set tmargin at screen 0.88
set bmargin at screen 0.12
set rmargin at screen 0.85
set tics scale 2.0, 1.0
set xtics font 'Malgun Gothic,9'
set ytics font 'Malgun Gothic,9'
set y2tics font 'Malgun Gothic,9'
set title "" font "Malgun Gothic,14" noenhanced
set xlabel "time" font "Malgun Gothic,11" noenhanced
set ylabel "pressure" font "Malgun Gothic,11" noenhanced
set y2label "temp1" font "Malgun Gothic,11" noenhanced
set ytics nomirror
set key enhanced at graph 0.1,0.5 box linewidth 1.5 opaque font "Malgun Gothic,9" samplen 3.5 spacing 1.2
plot \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):2 title "pressure" noenhanced axes x1y1 with lines lw 1.5 lc rgb "black", \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):3 title "flowrate" noenhanced axes x1y1 with lines lw 1.5 lc rgb "red" dashtype (8,4), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):4 title "temp1" noenhanced axes x1y2 with lines lw 1.5 lc rgb "blue" dashtype (2,3), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):5 title "temp2" noenhanced axes x1y2 with lines lw 1.5 lc rgb "green" dashtype (10,3,2,3), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):6 title "viodfr" noenhanced axes x1y2 with lines lw 1.5 lc rgb "magenta" dashtype (4,2)

pause mouse close