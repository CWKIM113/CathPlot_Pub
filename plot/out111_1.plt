set encoding utf8
set terminal windows title 'out111_1' font 'Malgun Gothic,11' size 1000,700
unset link y2
set xrange [0:2101]
set yrange [0:8]
set y2range [216:315]
set xtics auto
set ytics 2
set y2tics 25
unset mxtics
unset mytics
unset my2tics
set grid xtics ytics lw 1.5, lw 1.0
set mouse
set border lw 1.5
set lmargin at screen 0.12
set tmargin at screen 0.895
set bmargin at screen 0.12
set rmargin at screen 0.88
set tics scale 2.0, 1.0
set xtics font 'Malgun Gothic,9'
set ytics font 'Malgun Gothic,9'
set y2tics font 'Malgun Gothic,9'
set title "out111" font "Malgun Gothic,14" noenhanced
set xlabel "Time" font "Malgun Gothic,11" noenhanced
set ylabel "PRESS:PRSTNK(1)" font "Malgun Gothic,11" noenhanced
set y2label "TEMPF:PRSTNK(1)" font "Malgun Gothic,11" noenhanced
set ytics nomirror
unset key
set object 8000 rect from graph 0.7074,0.8910 to graph 0.9928,0.9928 fc rgb 'white' fs solid 1.0 border lc rgb 'black' lw 1.5 front
set arrow 8001 from graph 0.9154,0.9659 to graph 0.9778,0.9659 nohead front lc rgb "black" lw 1.5
set label 8001 "PRESS:PRSTNK(1)" at graph 0.9054,0.9659 right front font "Malgun Gothic,9" noenhanced
set arrow 8002 from graph 0.9154,0.9179 to graph 0.9778,0.9179 nohead front lc rgb "red" lw 1.5 dashtype (6,3)
set label 8002 "TEMPF:PRSTNK(1)" at graph 0.9054,0.9179 right front font "Malgun Gothic,9" noenhanced
plot \
"temp_sorted/out111_sortedX0.dat" using ($1+0.0):5 notitle axes x1y1 with lines lw 1.5 lc rgb "black", \
"temp_sorted/PZR_Para_sortedX0.dat" using ($1+0.0):8 notitle axes x1y2 with lines lw 1.5 lc rgb "red" dashtype (6,3)

pause mouse close