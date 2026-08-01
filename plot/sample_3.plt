set encoding utf8
set terminal windows title 'sample_3' font 'Malgun Gothic,11' size 1000,700
unset link y2
set xrange [0:1050]
set yrange [0:10]
set y2range [1:389]
set xtics auto
set ytics 2.5
set y2tics 100
unset mxtics
unset mytics
unset my2tics
set grid xtics ytics lw 1.5, lw 1.0
set mouse
set border lw 1.5
set lmargin at screen 0.12
set tmargin at screen 0.895
set bmargin at screen 0.16
set rmargin at screen 0.88
set tics scale 2.0, 1.0
set xtics font 'Malgun Gothic,9'
set ytics font 'Malgun Gothic,9'
set y2tics font 'Malgun Gothic,9'
set title "sample" font "Malgun Gothic,14" noenhanced
set xlabel "time" font "Malgun Gothic,11" noenhanced
set ylabel "pressure" font "Malgun Gothic,11" noenhanced
set y2label "temp1" font "Malgun Gothic,11" noenhanced
set ytics nomirror
unset key
set object 8000 rect from graph 0.8098,0.6822 to graph 0.9832,0.9760 fc rgb 'white' fs solid 1.0 border lc rgb 'black' lw 1.5 front
set arrow 8001 from graph 0.9058,0.9491 to graph 0.9682,0.9491 nohead front lc rgb "black" lw 1.5
set label 8001 "pressure" at graph 0.8958,0.9491 right front font "Malgun Gothic,9" noenhanced
set arrow 8002 from graph 0.9058,0.9011 to graph 0.9682,0.9011 nohead front lc rgb "red" lw 1.5 dashtype (6,3)
set label 8002 "viodfr" at graph 0.8958,0.9011 right front font "Malgun Gothic,9" noenhanced
set arrow 8003 from graph 0.9058,0.8531 to graph 0.9682,0.8531 nohead front lc rgb "blue" lw 1.5 dashtype (1,2)
set label 8003 "var_6" at graph 0.8958,0.8531 right front font "Malgun Gothic,9" noenhanced
set arrow 8004 from graph 0.9058,0.8051 to graph 0.9682,0.8051 nohead front lc rgb "green" lw 1.5 dashtype (6,2,1,2)
set label 8004 "temp1" at graph 0.8958,0.8051 right front font "Malgun Gothic,9" noenhanced
set arrow 8005 from graph 0.9058,0.7571 to graph 0.9682,0.7571 nohead front lc rgb "magenta" lw 1.5 dashtype (3,2)
set label 8005 "temp2" at graph 0.8958,0.7571 right front font "Malgun Gothic,9" noenhanced
set arrow 8006 from graph 0.9058,0.7091 to graph 0.9682,0.7091 nohead front lc rgb "cyan" lw 1.5 dashtype (6,2,1,2,1,2)
set label 8006 "var_7" at graph 0.8958,0.7091 right front font "Malgun Gothic,9" noenhanced
plot \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):2 notitle axes x1y1 with lines lw 1.5 lc rgb "black", \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):6 notitle axes x1y1 with lines lw 1.5 lc rgb "red" dashtype (6,3), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):7 notitle axes x1y1 with lines lw 1.5 lc rgb "blue" dashtype (1,2), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):4 notitle axes x1y2 with lines lw 1.5 lc rgb "green" dashtype (6,2,1,2), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):5 notitle axes x1y2 with lines lw 1.5 lc rgb "magenta" dashtype (3,2), \
"temp_sorted/sample_sortedX0.dat" using ($1+0.0):8 notitle axes x1y2 with lines lw 1.5 lc rgb "cyan" dashtype (6,2,1,2,1,2)

pause mouse close