# Loop Over Body Shapes
for R in 519 1320 521 523 779 365 1198 368 337 944 1333 502 344 538 413
do
	# Loop over Genders
	for GENDER in male female
	do
		# Loop over Pose_IDX for walking humans
		for i in 2 5 7 8 13 14 24 26 27 46 48 49 59 60 62 64 65
		do
			$BLENDER_PATH/blender -b -t 1 -P export_human_meshes.py -- --idx $i --ishape 0 --stride 50 --gender $GENDER --body_shape_idx $R --outdir human_meshes_v2
		done

		# Loop over Pose_IDX for stationary humans
		for i in 132 133 134 135 
		do
			$BLENDER_PATH/blender -b -t 1 -P export_human_meshes.py -- --idx $i --ishape 0 --stride 50 --gender $GENDER --body_shape_idx $R --outdir human_meshes_v2
		done

	done
done
