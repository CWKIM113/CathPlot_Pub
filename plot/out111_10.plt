set encoding utf8
set terminal windows title 'out111_10' font 'Malgun Gothic,11' size 1000,700
unset link y2
set logscale x
set logscale y
set logscale y2
set xrange [1:10000]
set yrange [0.1:10]
set y2range [1:1000]
set xtics auto
set ytics auto
set y2tics auto
set mxtics 10
set mytics 10
unset my2tics
set grid xtics ytics lw 1.5, lw 1.0
set mouse
set border lw 1.5
set lmargin at screen 0.12
set tmargin at screen 0.895
set bmargin at screen 0.18
set rmargin at screen 0.88
set tics scale 2.0, 1.0
set xtics font 'Malgun Gothic,9'
set ytics font 'Malgun Gothic,9'
set y2tics font 'Malgun Gothic,9'
set title "out111" font "Malgun Gothic,14" noenhanced
set xlabel "Time" font "Malgun Gothic,11" noenhanced
set ylabel "pressure" font "Malgun Gothic,11" noenhanced
set y2label "temp2" font "Malgun Gothic,11" noenhanced
set ytics nomirror
unset key
set object 8000 rect from graph 0.6890,0.7891 to graph 0.9888,0.9888 fc rgb 'white' fs solid 1.0 border lc rgb 'black' lw 1.5 front
set arrow 8001 from graph 0.8970,0.9610 to graph 0.9738,0.9610 nohead front lc rgb "black" lw 1.5
set label 8001 "pressure" at graph 0.8870,0.9610 right front font "Malgun Gothic,9" noenhanced
set arrow 8002 from graph 0.8970,0.9130 to graph 0.9738,0.9130 nohead front lc rgb "red" lw 1.5 dashtype (6,3)
set label 8002 "PRESS:PRSTNK(1)" at graph 0.8870,0.9130 right front font "Malgun Gothic,9" noenhanced
set arrow 8003 from graph 0.8970,0.8650 to graph 0.9738,0.8650 nohead front lc rgb "blue" lw 1.5 dashtype (1,2)
set label 8003 "temp2" at graph 0.8870,0.8650 right front font "Malgun Gothic,9" noenhanced
set arrow 8004 from graph 0.8970,0.8170 to graph 0.9738,0.8170 nohead front lc rgb "green" lw 1.5 dashtype (6,2,1,2)
set label 8004 "TEMPF:PRSTNK(1)" at graph 0.8870,0.8170 right front font "Malgun Gothic,9" noenhanced
plot \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):2 notitle axes x1y1 with lines lw 1.5 lc rgb "black", \
"temp_sorted/out111_sortedX0.dat" using ($1+0.0):5 notitle axes x1y1 with lines lw 1.5 lc rgb "red" dashtype (6,3), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):5 notitle axes x1y2 with lines lw 1.5 lc rgb "blue" dashtype (1,2), \
"temp_sorted/PZR_Para_sortedX0.dat" using ($1+0.0):8 notitle axes x1y2 with lines lw 1.5 lc rgb "green" dashtype (6,2,1,2)

pause mouse close